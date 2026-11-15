from fastapi.testclient import TestClient
from pharmacyflow.db import session
from pharmacyflow.models import Case, Patient, Policy, AgentInput, now
from pharmacyflow.security import Principal, token, action_hash
from pharmacyflow.mock_app import app as mock
from pharmacyflow.workflow import IntakeAgent
from pharmacyflow.worker import expire_waiting


def test_pending_action_deduplicated_across_keys(environment):
    action = {
        "kind": "refill_request",
        "tenant": "demo",
        "patient_id": "pat-001",
        "prescription_id": "rx-001",
        "fields": {},
    }
    p = Principal(
        sub="worker", tenant="demo", role="worker", patient_id="pat-001", case_id="c", agent="execution"
    )
    with TestClient(mock) as client:
        ids = []
        for key in ["first", "second"]:
            h = {
                "Authorization": "Bearer "
                + token(p, "mock", key=key, action=action, action_hash=action_hash(action), can_write=True)
            }
            assert client.post("/save", headers=h).status_code == 200
            ids.append(client.get("/api/requests/" + key, headers=h).json()["request"]["id"])
        assert ids[0] == ids[1]


def test_mock_rejects_readonly_and_expired_capability(environment):
    action = {
        "kind": "refill_request",
        "tenant": "demo",
        "patient_id": "pat-001",
        "prescription_id": "rx-001",
        "fields": {},
    }
    p = Principal(sub="worker", tenant="demo", role="worker", case_id="c")
    with TestClient(mock) as client:
        for seconds, write, expected in [(60, False, 403), (-1, True, 401)]:
            h = {
                "Authorization": "Bearer "
                + token(
                    p,
                    "mock",
                    seconds=seconds,
                    key="k",
                    action=action,
                    action_hash=action_hash(action),
                    can_write=write,
                )
            }
            assert client.post("/save", headers=h).status_code == expected


def test_timeout_and_cancel(client, auth, refill):
    c = refill()
    assert client.post("/api/cases/" + c["id"] + "/cancel", headers=auth()).json()["state"] == "cancelled"
    c = refill()
    with session() as db:
        row = db.get(Case, c["id"])
        row.created_at = now() - 10000
        db.commit()
    expire_waiting()
    assert client.get("/api/cases/" + c["id"], headers=auth()).json()["state"] == "timed_out"


async def test_ambiguous_exact_patient_requires_clarification(environment):
    from pharmacyflow.tool_service import invoke

    with session() as db:
        db.add(
            Patient(
                id="duplicate",
                tenant="demo",
                name="Avery Morgan",
                dob="1988-04-12",
                verification_code="000000",
            )
        )
        c = Case(
            tenant="demo",
            created_by="staff",
            kind="intake",
            state="record_lookup",
            request_key="ambiguous",
            payload={
                "extraction": {
                    "fields": {"patient_name": {"value": "Avery Morgan"}, "dob": {"value": "1988-04-12"}}
                }
            },
        )
        db.add(c)
        db.commit()

    class Local:
        async def call(self, tool_name, **args):
            t = token(
                Principal(sub="worker", tenant="demo", role="worker", case_id=c.id, agent="intake"), "mcp"
            )
            return invoke(t, tool_name, args)

    result = await IntakeAgent().run(
        AgentInput(case_id=c.id, tenant="demo", state="record_lookup"), c, Local()
    )
    assert result.state == "clarification" and result.evidence["match_count"] == 2


def test_missing_policy_blocks(environment):
    from pharmacyflow.retrieval import retrieve

    with session() as db:
        db.delete(db.get(Policy, "demo:review-v1"))
        db.commit()
        assert retrieve(db, "demo", "review")["blocked"]


async def test_retention_deletes_only_expired_terminal_cases(environment):
    from pharmacyflow.retention import purge

    with session() as db:
        c = Case(
            tenant="demo",
            created_by="staff",
            kind="intake",
            state="cancelled",
            request_key="retention",
            payload={},
            updated_at=now() - 60 * 86400,
        )
        db.add(c)
        db.commit()
        cid = c.id
    assert (await purge())["count"] == 1
    assert (await purge(dry_run=False))["count"] == 1
    with session() as db:
        assert db.get(Case, cid) is None


def test_metrics_have_inspectable_cases(client, auth, refill):
    c = refill(request_key="duplicate-metric")
    refill(request_key="duplicate-metric")
    r = client.get("/api/metrics", headers=auth("staff"))
    assert r.status_code == 200
    assert c["id"] in r.json()["measures"]["duplicate_prevention"]["case_ids"]
