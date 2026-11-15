"""Permission-checked tool implementation, shared by MCP and deterministic tests."""

import time
import httpx
from sqlalchemy import select
from fastapi import HTTPException
from .config import settings
from .db import session
from .models import Case, Patient, Prescription, Action
from .security import Principal, decode, accessible, action_hash, token
from .telemetry import audit
from .leases import fence
from .security import valid_approval

PERMISSIONS = {
    "intake": {"patient_lookup", "prescription_lookup", "workflow_task"},
    "execution": {"request_status", "prepare_transaction", "workflow_task"},
    "verification": {"patient_lookup", "prescription_lookup", "request_status", "workflow_task"},
    "single": {
        "patient_lookup",
        "prescription_lookup",
        "request_status",
        "prepare_transaction",
        "workflow_task",
    },
}


def context(auth: str, tool: str):
    data = decode(auth, "mcp")
    p = Principal.model_validate({k: data[k] for k in Principal.model_fields if k in data})
    if p.role != "worker" or tool not in PERMISSIONS.get(p.agent, set()) or not p.case_id:
        raise HTTPException(403, "Tool not allowed for this agent")
    return p


def invoke(auth: str, tool: str, arguments: dict | None = None):
    started = time.perf_counter()
    p = context(auth, tool)
    arguments = arguments or {}
    with session() as db:
        case = accessible(p, db.get(Case, p.case_id))
        fence(db, case.id, p.lease_owner)
        # Lock row on PostgreSQL; conditional update protects SQLite too.
        from sqlalchemy import update

        budget = db.execute(
            update(Case)
            .where(Case.id == case.id, Case.tool_calls < settings().max_tool_calls)
            .values(tool_calls=Case.tool_calls + 1)
        )
        if not budget.rowcount:
            raise HTTPException(429, "Case tool budget exceeded")
        db.commit()
        db.refresh(case)
        if tool == "patient_lookup":
            query = select(Patient).where(Patient.tenant == p.tenant)
            if case.patient_id:
                query = query.where(Patient.id == case.patient_id)
            else:
                query = query.where(
                    Patient.name == arguments.get("name"), Patient.dob == arguments.get("dob")
                )
            rows = list(db.scalars(query))
            result = {"matches": [{"id": r.id, "name": r.name, "dob": r.dob} for r in rows]}
        elif tool == "prescription_lookup":
            if not case.patient_id:
                raise HTTPException(403, "Patient selection required")
            rows = db.scalars(
                select(Prescription).where(
                    Prescription.tenant == p.tenant, Prescription.patient_id == case.patient_id
                )
            )
            result = {
                "prescriptions": [
                    {
                        "id": r.id,
                        "medication": r.medication,
                        "strength": r.strength,
                        "refills": r.refills,
                        "status": r.status,
                    }
                    for r in rows
                ]
            }
        elif tool in {"request_status", "prepare_transaction"}:
            if not case.action or case.action_hash != action_hash(case.action):
                raise HTTPException(409, "Action missing or changed")
            action = Action.model_validate(case.action)
            if action.tenant != case.tenant or action.patient_id != case.patient_id:
                raise HTTPException(403, "Action scope mismatch")
            if tool == "prepare_transaction":
                if case.state != "execution":
                    raise HTTPException(409, "Execution is not authorized in this state")
                if action.kind == "intake_draft" and (not valid_approval(db, case)):
                    raise HTTPException(403, "Exact pharmacist approval required")
                if action.kind == "refill_request" and not (
                    case.payload.get("identity_verified") and case.payload.get("selection_confirmed")
                ):
                    raise HTTPException(403, "Verified simulated identity required")
                if action.kind == "refill_request":
                    rx = db.get(Prescription, action.prescription_id)
                    if (
                        not rx
                        or rx.tenant != case.tenant
                        or rx.patient_id != case.patient_id
                        or rx.refills < 1
                        or rx.status != "active"
                    ):
                        raise HTTPException(403, "Prescription no longer eligible")
            seconds = (
                -1
                if tool == "prepare_transaction"
                and case.payload.get("fault") == "expired_session"
                and settings().allow_fault_injection
                else 120
            )
            mock_token = token(
                p,
                "mock",
                seconds=seconds,
                action_hash=case.action_hash,
                action=case.action,
                key=case.id,
                can_write=tool == "prepare_transaction",
                fault=case.payload.get("fault") if settings().allow_fault_injection else None,
            )
            if tool == "request_status":
                response = httpx.get(
                    settings().mock_url + "/api/requests/" + case.id,
                    headers={"Authorization": "Bearer " + mock_token},
                    timeout=5,
                )
                response.raise_for_status()
                result = response.json()
            else:
                result = {
                    "token": mock_token,
                    "key": case.id,
                    "action": case.action,
                    "action_hash": case.action_hash,
                }
        elif tool == "workflow_task":
            result = {
                "case_id": case.id,
                "state": case.state,
                "action_hash": case.action_hash,
                "approved": bool(case.approved_hash and case.approved_hash == case.action_hash),
            }
        else:
            raise HTTPException(403, "Unknown tool")
        audit(
            db,
            case,
            "agent:" + p.agent,
            "tool",
            tool,
            {"tool": tool, "count": len(result.get("matches", result.get("prescriptions", [])))},
            (time.perf_counter() - started) * 1000,
        )
        db.commit()
        return result
