from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from pharmacyflow.db import session
from pharmacyflow.models import Job, Case, User, AgentInput
from pharmacyflow.worker import claim
from pharmacyflow.leases import fence
from pharmacyflow.tool_service import invoke
from pharmacyflow.security import Principal, token, valid_approval
from pharmacyflow.config import settings
from pharmacyflow.accounts import create_account
from pharmacyflow.workflow import ExecutionAgent
from test_workflow import draft


def test_concurrent_exact_approvals_have_one_winner(client, auth):
    with session() as db:
        c = draft()
        db.add(c)
        db.commit()
        cid, digest = c.id, c.action_hash
    header = auth("pharmacist")

    def approve(_):
        return client.post(
            f"/api/cases/{cid}/approve", headers=header, json={"action_hash": digest, "attested": True}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, range(2))) == [200, 409]


async def test_outdated_worker_cannot_commit_after_ownership_loss(environment):
    from pharmacyflow.workflow import step
    from pharmacyflow.models import AgentOutput
    from pharmacyflow.leases import lease_owner

    with session() as db:
        c = draft()
        c.state = "preparation"
        db.add(c)
        db.flush()
        db.add(Job(case_id=c.id, status="ready"))
        db.commit()
        cid = c.id
    assert claim("old") == cid

    class Interrupted:
        name = "intake"

        async def run(self, request, case, tools):
            with session() as db:
                db.get(Job, cid).lease_owner = "replacement"
                db.commit()
            return AgentOutput(state="completed", reason="outdated_result")

    context = lease_owner.set("old")
    try:
        with pytest.raises(HTTPException):
            await step({"case_id": cid, "state": "preparation", "revision": 0}, Interrupted)
    finally:
        lease_owner.reset(context)
    with session() as db:
        assert db.get(Case, cid).state == "preparation"


def test_stale_browser_capability_cannot_write(environment):
    from fastapi.testclient import TestClient
    from pharmacyflow.mock_app import app
    from pharmacyflow.models import MockRequest
    from sqlalchemy import select

    with session() as db:
        c = draft()
        c.state = "execution"
        db.add(c)
        db.flush()
        db.add(Job(case_id=c.id, status="ready"))
        db.commit()
        cid = c.id
    assert claim("new-owner") == cid
    capability = token(
        Principal(
            sub="worker",
            role="worker",
            tenant="demo",
            case_id=cid,
            agent="execution",
            lease_owner="old-owner",
        ),
        "mock",
        action=c.action,
        action_hash=c.action_hash,
        key=cid,
        can_write=True,
    )
    with TestClient(app) as browser:
        assert browser.post("/save", headers={"Authorization": "Bearer " + capability}).status_code == 409
    with session(settings().mock_database_url) as db:
        assert db.scalar(select(MockRequest)) is None


def test_competing_workers_and_fenced_old_claim(environment):
    with session() as db:
        c = draft()
        db.add(c)
        db.flush()
        db.add(Job(case_id=c.id))
        db.commit()
        cid = c.id
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["first", "second"]))
    assert sum(x == cid for x in results) == 1
    with session() as db:
        j = db.get(Job, cid)
        old_owner = j.lease_owner
        j.lease_until = 0
        db.commit()
    assert claim("replacement") == cid
    stale = token(
        Principal(
            sub="worker", tenant="demo", role="worker", case_id=cid, agent="intake", lease_owner=old_owner
        ),
        "mcp",
    )
    with pytest.raises(HTTPException) as error:
        invoke(stale, "workflow_task")
    assert error.value.status_code == 409
    with session() as db:
        with pytest.raises(HTTPException):
            fence(db, cid, old_owner, lock=True)
        fence(db, cid, "replacement", lock=True)


def test_individual_accounts_demo_disabled_and_revocation(client, auth):
    with session() as db:
        db.get(User, "pharmacist").demo_account = 1
        db.commit()
    settings().demo_mode = False
    assert (
        client.post(
            "/api/login", json={"username": "pharmacist", "password": "test-password-123"}
        ).status_code
        == 401
    )
    create_account("individual-reviewer", "a-different-long-password", "demo", "pharmacist")
    result = client.post(
        "/api/login", json={"username": "individual-reviewer", "password": "a-different-long-password"}
    )
    assert result.status_code == 200
    headers = {"Authorization": "Bearer " + result.json()["token"]}
    assert client.get("/api/me", headers=headers).status_code == 200
    assert client.post("/api/logout", headers=headers).status_code == 200
    assert client.get("/api/me", headers=headers).status_code == 401


async def test_expired_approval_returns_to_review_without_write(client, auth):
    with session() as db:
        c = draft()
        db.add(c)
        db.commit()
        cid, digest = c.id, c.action_hash
    r = client.post(
        f"/api/cases/{cid}/approve",
        headers=auth("pharmacist"),
        json={"action_hash": digest, "attested": True},
    )
    assert r.status_code == 200
    with session() as db:
        c = db.get(Case, cid)
        c.payload = {**c.payload, "approval": {**c.payload["approval"], "expires_at": 0}}
        db.commit()
        assert not valid_approval(db, c)

    class ReadOnly:
        async def call(self, name, **kw):
            assert name == "request_status", "expired approval attempted a write tool"
            return {"request": None}

    result = await ExecutionAgent().run(
        AgentInput(case_id=cid, tenant="demo", state="execution"), c, ReadOnly()
    )
    assert result.state == "review"
