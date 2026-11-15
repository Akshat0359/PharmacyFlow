import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from .config import settings
from .db import session
from .models import Case, AgentInput, AgentOutput, Action, State, TERMINAL, FIELD_NAMES, now
from .security import action_hash
from .telemetry import audit
from .mcp_client import Tools
from .providers import Provider
from .retrieval import retrieve
from .browser import transact
from .leases import fence, lease_owner
from .security import valid_approval
from .metering import usage_context


def transition(db, case, output: AgentOutput, agent: str):
    old = case.state
    case.state = output.state
    case.updated_at = now()
    case.revision += 1
    audit(
        db,
        case,
        "agent:" + agent,
        "transition",
        output.reason,
        {"from": old, "to": output.state, "reason": output.reason, **output.evidence},
    )


def prepare(case):
    if case.kind == "refill":
        action = Action(
            kind="refill_request",
            tenant=case.tenant,
            patient_id=case.patient_id,
            prescription_id=case.payload["prescription_id"],
        )
    else:
        action = Action(
            kind="intake_draft",
            tenant=case.tenant,
            patient_id=case.patient_id,
            fields={
                k: v.get("value") for k, v in case.payload["extraction"]["fields"].items() if k in FIELD_NAMES
            },
        )
    case.action = action.model_dump()
    case.action_hash = action_hash(case.action)
    case.approved_hash = None
    case.approved_by = None
    case.payload = {**case.payload, "approval": None}


async def model_assessment(case, agent, evidence):
    provider = Provider()
    decision = await asyncio.to_thread(
        provider.agent_decision, agent, evidence, case.payload.get("citations", [])
    )
    usage = dict(case.payload.get("usage", {}))
    for key in ["tokens_in", "tokens_out", "estimated_cost_usd"]:
        usage[key] = usage.get(key, 0) + provider.usage.get(key, 0)
    case.payload = {
        **case.payload,
        "usage": usage,
        "agent_decisions": {
            **case.payload.get("agent_decisions", {}),
            agent: {**decision.model_dump(), "mode": provider.cfg.provider_mode},
        },
    }
    return decision


class IntakeAgent:
    name = "intake"

    async def run(self, request: AgentInput, case, tools) -> AgentOutput:
        if case.state == State.INTAKE:
            provider = Provider()
            extraction = await asyncio.to_thread(
                provider.extract, Path(case.payload["document_path"]).read_bytes(), case.payload["mime"]
            )
            case.payload = {**case.payload, "extraction": extraction.model_dump(), "usage": provider.usage}
            return AgentOutput(state=State.LOOKUP, reason="extraction_ready", evidence=provider.usage)
        if case.state == State.LOOKUP:
            fields = case.payload.get("extraction", {}).get("fields", {})
            result = await tools.call(
                "patient_lookup",
                name=fields.get("patient_name", {}).get("value") or "",
                dob=fields.get("dob", {}).get("value") or "",
            )
            matches = result["matches"]
            if len(matches) != 1:
                return AgentOutput(
                    state=State.CLARIFICATION,
                    reason="patient_match_requires_clarification",
                    evidence={"match_count": len(matches)},
                )
            case.patient_id = matches[0]["id"]
            if case.kind == "refill":
                rx = await tools.call("prescription_lookup")
                selected = [r for r in rx["prescriptions"] if r["id"] == case.payload.get("prescription_id")]
                if (
                    len(selected) != 1
                    or not case.payload.get("identity_verified")
                    or not case.payload.get("selection_confirmed")
                ):
                    return AgentOutput(state=State.CLARIFICATION, reason="confirm_identity_and_prescription")
                if selected[0]["refills"] < 1 or selected[0]["status"] != "active":
                    return AgentOutput(state=State.ESCALATED, reason="refill_unavailable")
            return AgentOutput(
                state=State.PREPARATION, reason="patient_and_record_matched", evidence={"match_count": 1}
            )
        if case.state == State.PREPARATION:
            prepare(case)
            provider = Provider()
            summary = await asyncio.to_thread(
                provider.policy_summary, case.action, case.payload.get("citations", [])
            )
            usage = dict(case.payload.get("usage", {}))
            for key in ["tokens_in", "tokens_out", "estimated_cost_usd"]:
                usage[key] = usage.get(key, 0) + provider.usage.get(key, 0)
            case.payload = {**case.payload, "policy_summary": summary, "usage": usage}
            return AgentOutput(
                state=State.REVIEW if case.kind == "intake" else State.EXECUTION, reason="draft_prepared"
            )
        raise ValueError("Invalid intake state")


class ExecutionAgent:
    name = "execution"

    async def run(self, request: AgentInput, case, tools) -> AgentOutput:
        # ALWAYS reconcile before browser use, including after process death.
        status = await tools.call("request_status")
        saved = status.get("request")
        if saved:
            if saved["action_hash"] != case.action_hash:
                return AgentOutput(state=State.ESCALATED, reason="persisted_action_conflict")
            case.result = saved
            return AgentOutput(
                state=State.VERIFICATION,
                reason="reconciled_existing_request",
                evidence={"duplicate_prevented": True, "request_id": saved["id"]},
            )
        if case.kind == "intake":
            with session() as db:
                if not valid_approval(db, case):
                    case.approved_by = case.approved_hash = None
                    return AgentOutput(state=State.REVIEW, reason="approval_expired_requires_review")
        decision = await model_assessment(
            case,
            "execution",
            {
                "action": case.action,
                "prior_request": saved,
                "identity_confirmed": case.payload.get("identity_verified"),
                "approved": bool(case.approved_by),
            },
        )
        if decision.decision == "escalate":
            return AgentOutput(state=State.ESCALATED, reason="execution_model_requires_review")
        prepared = await tools.call("prepare_transaction")
        case.result = await transact(prepared, case.payload.get("fault"))
        return AgentOutput(
            state=State.VERIFICATION,
            reason="browser_saved_and_read_back",
            evidence={"request_id": case.result["id"]},
        )


class VerificationAgent:
    name = "verification"

    async def run(self, request: AgentInput, case, tools) -> AgentOutput:
        saved = (await tools.call("request_status")).get("request")
        if not saved or saved["action_hash"] != case.action_hash or saved["patient_id"] != case.patient_id:
            return AgentOutput(state=State.ESCALATED, reason="verification_persisted_state_mismatch")
        if case.action_hash != action_hash(case.action):
            return AgentOutput(state=State.ESCALATED, reason="verification_action_changed")
        if case.kind == "intake":
            if (
                case.approved_hash != case.action_hash
                or not case.approved_by
                or any(not case.action["fields"].get(k) for k in FIELD_NAMES)
            ):
                return AgentOutput(state=State.ESCALATED, reason="verification_approval_or_fields_invalid")
            if case.mode == "multi":
                fields = case.payload["extraction"]["fields"]
                corrected = case.payload.get("corrected_fields", [])
                if any(
                    (not f.get("evidence") or f.get("confidence", 0) < 0.85 or f.get("issue"))
                    and k not in corrected
                    for k, f in fields.items()
                ):
                    return AgentOutput(state=State.ESCALATED, reason="verification_unresolved_source")
        else:
            if not case.payload.get("identity_verified") or not case.payload.get("selection_confirmed"):
                return AgentOutput(state=State.ESCALATED, reason="verification_identity_missing")
            if case.mode == "multi":
                result = await tools.call("prescription_lookup")
                if not any(r["id"] == case.action["prescription_id"] for r in result["prescriptions"]):
                    return AgentOutput(state=State.ESCALATED, reason="verification_prescription_mismatch")
        case.result = saved
        decision = await model_assessment(
            case,
            "verification",
            {
                "action": case.action,
                "persisted": saved,
                "source": case.payload.get("extraction"),
                "corrections": case.payload.get("corrected_fields", []),
            },
        )
        if decision.decision == "escalate":
            return AgentOutput(state=State.ESCALATED, reason="verification_model_requires_review")
        return AgentOutput(
            state=State.COMPLETED,
            reason="verified_recorded_for_pharmacist",
            evidence={"request_id": saved["id"], "status": saved["status"]},
        )


class GraphState(TypedDict):
    case_id: str
    state: str
    revision: int


async def step(state: GraphState, agent_cls):
    with session() as db:
        fence(db, state["case_id"], lease_owner.get())
        case = db.get(Case, state["case_id"])
        if case.state in TERMINAL or case.state in {State.REVIEW, State.IDENTITY, State.CLARIFICATION}:
            return {"state": case.state, "revision": case.revision}
        original_revision = case.revision
        usage_context.set(
            {**usage_context.get(), "tenant": case.tenant, "case_id": case.id, "actor": agent_cls.name}
        )
        started = time.perf_counter()
        if now() - case.created_at > settings().workflow_timeout_seconds:
            # An expired deadline never erases an uncertain external write.
            saved = None
            if case.state in {State.EXECUTION, State.VERIFICATION} and case.action:
                saved = (
                    await Tools(case, "single" if case.mode == "single" else "execution").call(
                        "request_status"
                    )
                ).get("request")
            if not saved:
                transition(
                    db, case, AgentOutput(state=State.TIMED_OUT, reason="workflow_timeout"), "scheduler"
                )
                db.commit()
                return {"state": case.state, "revision": case.revision}
        policies = await asyncio.to_thread(
            retrieve, db, case.tenant, "refill review identity recovery", case.payload.get("policy_version", "1")
        )
        case.payload = {**case.payload, "citations": policies["citations"]}
        agent = agent_cls()
        identity = "single" if case.mode == "single" else agent.name
        audit(
            db,
            case,
            "agent:" + identity,
            "retrieval",
            "policy_retrieval",
            {
                "policy_ids": [c["document_id"] for c in policies["citations"]],
                "version": case.payload.get("policy_version", "1"),
            },
        )
        # Persist context before tools open independent database transactions.
        db.commit()
        if policies["blocked"]:
            output = AgentOutput(state=State.ESCALATED, reason="policy_context_untrusted_or_missing")
        else:
            output = await agent.run(
                AgentInput(case_id=case.id, tenant=case.tenant, state=case.state), case, Tools(case, identity)
            )
        # A human cancellation/edit wins over a stale worker response.
        with session() as check:
            current = check.get(Case, case.id)
            if current.revision != original_revision or current.state in TERMINAL:
                db.rollback()
                return {"state": current.state, "revision": current.revision}
        transition(db, case, output, identity)
        fence(db, case.id, lease_owner.get(), lock=True)
        audit(
            db,
            case,
            "agent:" + identity,
            "stage",
            "stage_completed",
            {"agent": agent.name, "mode": settings().provider_mode},
            (time.perf_counter() - started) * 1000,
        )
        if output.reason == "browser_saved_and_read_back":
            audit(
                db,
                case,
                "agent:" + identity,
                "browser",
                "visible_ui_transaction",
                {
                    "tool": "playwright",
                    "action_hash": case.action_hash,
                    "request_id": case.result["id"],
                    "status": case.result["status"],
                    "count": 4,
                },
            )
        db.commit()
        return {"state": case.state, "revision": case.revision}


def build_graph(saver):
    async def intake(s):
        return await step(s, IntakeAgent)

    async def execution(s):
        return await step(s, ExecutionAgent)

    async def verification(s):
        return await step(s, VerificationAgent)

    graph = StateGraph(GraphState)
    graph.add_node("intake", intake)
    graph.add_node("execution", execution)
    graph.add_node("verification", verification)
    graph.add_conditional_edges(
        START,
        lambda s: (
            "execution"
            if s["state"] == State.EXECUTION
            else "verification"
            if s["state"] == State.VERIFICATION
            else "intake"
        ),
    )
    for node in ["intake", "execution", "verification"]:
        graph.add_edge(node, END)
    return graph.compile(checkpointer=saver)


@asynccontextmanager
async def durable_graph():
    url = settings().checkpoint_url
    if url.startswith("sqlite:///"):
        async with AsyncSqliteSaver.from_conn_string(url.removeprefix("sqlite:///")) as saver:
            await saver.setup()
            yield build_graph(saver)
    else:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(
            url.replace("postgresql+psycopg", "postgresql")
        ) as saver:
            await saver.setup()
            yield build_graph(saver)
