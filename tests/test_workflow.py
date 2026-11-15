from pharmacyflow.db import session
from pharmacyflow.models import Case, Job, State, FIELD_NAMES, AgentInput
from pharmacyflow.providers import parse_text
from pharmacyflow.workflow import prepare, VerificationAgent, durable_graph
from pharmacyflow.worker import claim


def draft():
    fields = "\n".join(
        f"{k}: " + ({"patient_name": "Avery Morgan", "dob": "1988-04-12"}.get(k, "demo")) for k in FIELD_NAMES
    )
    c = Case(
        tenant="demo",
        created_by="staff",
        patient_id="pat-001",
        kind="intake",
        state=State.REVIEW,
        request_key="draft-test",
        payload={"extraction": parse_text([fields]).model_dump()},
    )
    prepare(c)
    return c


def test_approval_bound_to_action_and_invalidated(client, auth):
    with session() as db:
        c = draft()
        db.add(c)
        db.commit()
        cid = c.id
        old = c.action_hash
    h = auth("pharmacist")
    r = client.patch(
        "/api/cases/" + cid + "/fields", headers=h, json={"fields": {"quantity": "31"}, "revision": 0}
    )
    assert r.status_code == 200, r.text
    assert r.json()["action_hash"] != old and r.json()["approved_by"] is None
    assert (
        client.post(
            "/api/cases/" + cid + "/approve", headers=h, json={"action_hash": old, "attested": True}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/cases/" + cid + "/approve",
            headers=h,
            json={"action_hash": r.json()["action_hash"], "attested": True},
        ).status_code
        == 200
    )


def test_unresolved_fields_cannot_be_approved(client, auth):
    with session() as db:
        c = draft()
        c.payload = {**c.payload, "extraction": parse_text(["patient_name: Avery Morgan"]).model_dump()}
        prepare(c)
        db.add(c)
        db.commit()
        cid = c.id
        hash = c.action_hash
    assert (
        client.post(
            "/api/cases/" + cid + "/approve",
            headers=auth("pharmacist"),
            json={"action_hash": hash, "attested": True},
        ).status_code
        == 422
    )


def test_atomic_claim_and_expired_lease_recovery(environment):
    with session() as db:
        db.add(Job(case_id="job"))
        db.commit()
    assert claim("first") == "job"
    assert claim("second") is None
    with session() as db:
        j = db.get(Job, "job")
        j.lease_until = 0
        db.commit()
    assert claim("second") == "job"


async def test_langgraph_checkpoint_survives_reopen(environment):
    with session() as db:
        c = draft()
        db.add(c)
        db.commit()
        cid = c.id
    config = {"configurable": {"thread_id": cid}}
    async with durable_graph() as graph:
        await graph.ainvoke({"case_id": cid, "state": "review", "revision": 0}, config)
    async with durable_graph() as graph:
        snapshot = await graph.aget_state(config)
        assert snapshot.values["case_id"] == cid
        assert snapshot.values["state"] == "review"


async def test_verifier_rejects_wrong_saved_patient(environment):
    class FakeTools:
        async def call(self, *args, **kwargs):
            return {"request": {"patient_id": "pat-002", "action_hash": "wrong"}}

    c = draft()
    c.id = "case"
    c.mode = "multi"
    result = await VerificationAgent().run(
        AgentInput(case_id=c.id, tenant=c.tenant, state="verification"), c, FakeTools()
    )
    assert result.state == "escalated"
