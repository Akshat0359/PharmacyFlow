import pytest
from fastapi import HTTPException
from sqlalchemy import select
from pharmacyflow.models import Case, Event
from pharmacyflow.db import session
from pharmacyflow.security import Principal, token
from pharmacyflow.tool_service import invoke


def test_identity_cross_patient_and_tenant(client, auth, refill):
    c = refill()
    assert client.get("/api/cases/" + c["id"], headers=auth("other-patient")).status_code == 404
    r = client.post(
        "/api/cases/" + c["id"] + "/identity",
        headers=auth(),
        json={"dob": "1988-04-12", "code": "246810", "confirmed": True},
    )
    assert r.status_code == 200
    for rx in ["rx-002", "other-rx-001"]:
        assert (
            client.post(
                "/api/cases/" + c["id"] + "/select",
                headers=auth(),
                json={"prescription_id": rx, "confirmed": True},
            ).status_code
            == 404
        )


def test_identity_bounded_attempts(client, auth, refill):
    c = refill()
    h = auth()
    for _ in range(3):
        assert (
            client.post(
                "/api/cases/" + c["id"] + "/identity",
                headers=h,
                json={"dob": "2000-01-01", "code": "no", "confirmed": True},
            ).status_code
            == 403
        )
    assert client.get("/api/cases/" + c["id"], headers=h).json()["state"] == "escalated"


def test_idempotent_creation(client, auth, refill):
    first = refill(request_key="same-key-123")
    second = refill(request_key="same-key-123")
    assert first["id"] == second["id"]
    with session() as db:
        assert len(list(db.scalars(select(Case)))) == 1


def test_patient_cannot_upload_or_approve(client, auth, refill):
    assert (
        client.post(
            "/api/intakes",
            headers=auth(),
            files={"file": ("evil.html", b"<script>bad()</script>", "text/html")},
            data={"request_key": "malicious-123"},
        ).status_code
        == 403
    )
    c = refill()
    assert (
        client.post(
            "/api/cases/" + c["id"] + "/approve",
            headers=auth("staff"),
            json={"action_hash": "bad", "attested": True},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "mime,data",
    [
        ("image/png", b"<script>alert(1)</script>"),
        ("application/pdf", b"not a pdf"),
        ("text/html", b"%PDF-1.7"),
    ],
)
def test_malicious_uploads(client, auth, mime, data):
    r = client.post(
        "/api/intakes",
        headers=auth("staff"),
        files={"file": ("x", data, mime)},
        data={"request_key": "upload-key-123"},
    )
    assert r.status_code == 422


def test_scoped_tool_permissions_and_budget(environment):
    from pharmacyflow.config import settings

    with session() as db:
        c = Case(
            tenant="demo",
            created_by="patient",
            patient_id="pat-001",
            kind="refill",
            state="identity_verification",
            request_key="tool-test",
            payload={},
        )
        db.add(c)
        db.commit()
        cid = c.id
    auth = token(
        Principal(
            sub="worker", tenant="demo", role="worker", patient_id="pat-001", case_id=cid, agent="intake"
        ),
        "mcp",
    )
    with pytest.raises(HTTPException) as err:
        invoke(auth, "prepare_transaction")
    assert err.value.status_code == 403
    assert [p["id"] for p in invoke(auth, "patient_lookup", {"name": "other", "dob": "bad"})["matches"]] == [
        "pat-001"
    ]
    with session() as db:
        c = db.get(Case, cid)
        c.tool_calls = settings().max_tool_calls
        db.commit()
    with pytest.raises(HTTPException) as err:
        invoke(auth, "workflow_task")
    assert err.value.status_code == 429


def test_expired_and_cross_case_capabilities(environment):
    p = Principal(sub="worker", tenant="other", role="worker", case_id="missing", agent="single")
    with pytest.raises(HTTPException):
        invoke(token(p, "mcp", seconds=-1), "workflow_task")
    with pytest.raises(HTTPException):
        invoke(token(p, "mcp"), "workflow_task")


def test_audit_redaction(environment):
    from pharmacyflow.telemetry import audit

    with session() as db:
        c = Case(
            tenant="demo",
            created_by="patient",
            patient_id="pat-001",
            kind="refill",
            request_key="audit-test",
            payload={},
        )
        db.add(c)
        db.flush()
        audit(
            db,
            c,
            "patient",
            "tool",
            "test",
            {"patient_name": "secret", "transcript": "secret", "token": "secret", "count": 1},
        )
        db.commit()
        assert list(db.scalars(select(Event)))[0].evidence == {"count": 1, "mode": "fixture"}
