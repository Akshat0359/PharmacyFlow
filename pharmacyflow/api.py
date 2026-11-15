import asyncio
import hashlib
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from pwdlib import PasswordHash
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from fastapi.responses import JSONResponse
from .config import settings
from .db import get_db
from .models import (
    User,
    Patient,
    Prescription,
    Case,
    Event,
    Job,
    State,
    TERMINAL,
    Strict,
    FIELD_NAMES,
    Evaluation,
    JudgeLabel,
    now,
    ProviderUsage,
    Budget,
)
from .security import Auth, Principal, token, require, accessible, action_hash
from .telemetry import audit, configure
from .providers import Provider, validate_document, validate_audio, MAX_BYTES
from .worker import enqueue
from .workflow import prepare
from .metering import usage_context, BudgetExceeded
from .limits import rate_limit


@asynccontextmanager
async def lifespan(app):
    settings().validate_runtime()
    configure()
    yield


app = FastAPI(title="PharmacyFlow AI • Synthetic demonstration", lifespan=lifespan)


@app.exception_handler(StaleDataError)
async def stale_update(request: Request, exc: StaleDataError):
    return JSONResponse(
        status_code=409, content={"detail": "The case changed concurrently. Reload it before retrying."}
    )


@app.exception_handler(BudgetExceeded)
async def budget_error(request: Request, exc: BudgetExceeded):
    return JSONResponse(status_code=429, content={"detail": str(exc)})


DB = Annotated[Session, Depends(get_db)]
login_attempts = defaultdict(list)


@app.middleware("http")
async def headers(request, call_next):
    if int(request.headers.get("content-length", "0")) > 11 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"detail": "Request exceeds upload limit"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; frame-src 'self' blob:; connect-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/health")
def health():
    return {
        "status": "ok",
        "synthetic": True,
        "mode": settings().provider_mode,
        "demo_accounts": settings().demo_mode,
    }


@app.get("/ready")
def ready(db: DB):
    db.execute(text("SELECT 1"))
    db.execute(select(User.id).limit(1))
    return {"status": "ready", "database": db.bind.dialect.name}


class Login(Strict):
    username: str = Field(max_length=80)
    password: str = Field(max_length=256)


@app.post("/api/login")
def login(body: Login, request: Request, db: DB):
    rate_limit(request.client.host, "login-source", 60)
    key = request.client.host + ":" + body.username
    login_attempts[key] = [t for t in login_attempts[key] if now() - t < 60]
    if len(login_attempts[key]) >= 12:
        raise HTTPException(429, "Too many sign-in attempts; retry in one minute")
    login_attempts[key].append(now())
    user = db.scalar(select(User).where(User.username == body.username))
    if (
        not user
        or user.disabled
        or (user.demo_account and not settings().demo_mode)
        or not PasswordHash.recommended().verify(body.password, user.password_hash)
    ):
        raise HTTPException(401, "Invalid credentials")
    p = Principal(sub=user.id, tenant=user.tenant, role=user.role, patient_id=user.patient_id)
    return {
        "token": token(p, seconds=settings().session_seconds, session_version=user.session_version),
        "user": p.model_dump(),
        "mode": settings().provider_mode,
        "synthetic": True,
    }


@app.post("/api/logout")
def logout(p: Auth, db: DB):
    user = db.get(User, p.sub)
    user.session_version += 1
    db.commit()
    return {"revoked": True}


@app.get("/api/me")
def me(p: Auth):
    return {**p.model_dump(), "mode": settings().provider_mode}


def case_json(c):
    payload = {k: v for k, v in c.payload.items() if k not in {"document_path"}}
    return {
        "id": c.id,
        "kind": c.kind,
        "state": c.state,
        "patient_id": c.patient_id,
        "mode": c.mode,
        "payload": payload,
        "action": c.action,
        "action_hash": c.action_hash,
        "approved_by": c.approved_by,
        "result": c.result,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "revision": c.revision,
        "tool_calls": c.tool_calls,
    }


@app.get("/api/cases")
def cases(p: Auth, db: DB):
    query = select(Case).where(Case.tenant == p.tenant)
    if p.role == "patient":
        query = query.where(Case.patient_id == p.patient_id)
    return [case_json(c) for c in db.scalars(query.order_by(Case.created_at.desc()).limit(250))]


@app.get("/api/cases/{case_id}")
def detail(case_id: str, p: Auth, db: DB):
    c = accessible(p, db.get(Case, case_id))
    events = db.scalars(
        select(Event).where(Event.case_id == case_id, Event.tenant == p.tenant).order_by(Event.created_at)
    )
    return {
        **case_json(c),
        "events": [
            {
                "id": e.id,
                "actor": e.actor,
                "category": e.category,
                "name": e.name,
                "evidence": e.evidence,
                "trace_id": e.trace_id,
                "trace_url": settings().trace_viewer_url.rstrip("/") + "/trace/" + e.trace_id
                if settings().trace_viewer_url and e.trace_id
                else None,
                "duration_ms": e.duration_ms,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }


class Refill(Strict):
    message: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=8, max_length=80)
    mode: Literal["single", "multi"] = "multi"
    fault: (
        Literal[
            "timeout_after_write",
            "changed_selector",
            "expired_session",
            "slow_page",
            "missing_element",
            "incorrect_patient",
            "browser_crash",
        ]
        | None
    ) = None


@app.post("/api/refills", status_code=201)
def refill(body: Refill, p: Auth, db: DB):
    require(p, "patient")
    existing = db.scalar(
        select(Case).where(
            Case.tenant == p.tenant, Case.created_by == p.sub, Case.request_key == body.request_key
        )
    )
    if existing:
        audit(
            db, existing, p.sub, "idempotency", "duplicate_request_prevented", {"duplicate_prevented": True}
        )
        db.commit()
        return case_json(existing)
    provider = Provider()
    usage_context.set({"tenant": p.tenant, "actor": p.sub})
    intent = provider.interpret(body.message)
    c = Case(
        tenant=p.tenant,
        created_by=p.sub,
        patient_id=p.patient_id,
        kind="refill",
        state=State.IDENTITY,
        request_key=body.request_key,
        mode=body.mode,
        payload={
            "provider_mode": settings().provider_mode,
            "intent": intent,
            "identity_verified": False,
            "selection_confirmed": False,
            "fault": body.fault if settings().allow_fault_injection else None,
            "usage": provider.usage,
            "conversation": [
                {"role": "patient", "text": body.message},
                {
                    "role": "assistant",
                    "text": "Confirm your synthetic date of birth and demo code, then confirm the prescription. No dispensing decision will be made.",
                },
            ],
        },
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return case_json(
            db.scalar(
                select(Case).where(
                    Case.tenant == p.tenant, Case.created_by == p.sub, Case.request_key == body.request_key
                )
            )
        )
    audit(db, c, p.sub, "transition", "refill_started", {"to": State.IDENTITY, **provider.usage})
    db.commit()
    return case_json(c)


class Identity(Strict):
    dob: str = Field(max_length=10)
    code: str = Field(max_length=20)
    confirmed: bool


@app.post("/api/cases/{case_id}/identity")
def identity(case_id: str, body: Identity, p: Auth, db: DB):
    require(p, "patient")
    c = accessible(p, db.get(Case, case_id))
    if c.state != State.IDENTITY:
        raise HTTPException(409, "Identity step is not active")
    patient = db.get(Patient, p.patient_id)
    good = body.confirmed and body.dob == patient.dob and body.code == patient.verification_code
    tries = c.payload.get("identity_attempts", 0) + 1
    c.payload = {**c.payload, "identity_attempts": tries, "identity_verified": good}
    if not good:
        c.revision += 1
        if tries >= 3:
            c.state = State.ESCALATED
        audit(db, c, p.sub, "identity", "identity_failed", {"attempt": tries})
        db.commit()
        raise HTTPException(
            403, "Synthetic identity did not match" if tries < 3 else "Identity attempts exhausted; escalated"
        )
    c.state = State.CLARIFICATION
    c.updated_at = now()
    c.revision += 1
    audit(db, c, p.sub, "identity", "identity_confirmed", {"to": c.state})
    db.commit()
    return {
        "case": case_json(c),
        "prescriptions": [
            {"id": r.id, "medication": r.medication, "strength": r.strength, "refills": r.refills}
            for r in db.scalars(
                select(Prescription).where(
                    Prescription.patient_id == p.patient_id, Prescription.tenant == p.tenant
                )
            )
        ],
    }


@app.get("/api/cases/{case_id}/prescriptions")
def prescriptions(case_id: str, p: Auth, db: DB):
    c = accessible(p, db.get(Case, case_id))
    if not c.payload.get("identity_verified"):
        raise HTTPException(403, "Confirm identity first")
    return [
        {"id": r.id, "medication": r.medication, "strength": r.strength, "refills": r.refills}
        for r in db.scalars(
            select(Prescription).where(
                Prescription.patient_id == c.patient_id, Prescription.tenant == p.tenant
            )
        )
    ]


class Selection(Strict):
    prescription_id: str
    confirmed: bool


@app.post("/api/cases/{case_id}/select")
def select_rx(case_id: str, body: Selection, p: Auth, db: DB):
    require(p, "patient")
    c = accessible(p, db.get(Case, case_id))
    if c.state != State.CLARIFICATION or not c.payload.get("identity_verified") or not body.confirmed:
        raise HTTPException(409, "Identity and explicit prescription confirmation required")
    rx = db.get(Prescription, body.prescription_id)
    if not rx or rx.tenant != p.tenant or rx.patient_id != p.patient_id:
        raise HTTPException(404, "Prescription unavailable")
    c.payload = {**c.payload, "selection_confirmed": True, "prescription_id": rx.id}
    c.state = State.LOOKUP
    c.revision += 1
    c.updated_at = now()
    enqueue(db, c)
    audit(db, c, p.sub, "transition", "prescription_confirmed", {"to": c.state})
    db.commit()
    return case_json(c)


@app.post("/api/intakes", status_code=201)
async def intake(
    p: Auth,
    db: DB,
    file: UploadFile = File(...),
    request_key: str = Form(...),
    document_context: str = Form("default"),
):
    require(p, "staff", "pharmacist", "administrator")
    if not 8 <= len(request_key) <= 80:
        raise HTTPException(422, "Invalid request key")
    existing = db.scalar(
        select(Case).where(Case.tenant == p.tenant, Case.created_by == p.sub, Case.request_key == request_key)
    )
    if existing:
        return case_json(existing)
    data = await file.read(MAX_BYTES + 1)
    try:
        kind = validate_document(data, file.content_type)
    except Exception:
        raise HTTPException(
            422, "Invalid document: use an unencrypted PDF (1–10 pages), PNG or JPEG up to 10 MB"
        ) from None
    if not 1 <= len(document_context) <= 80:
        raise HTTPException(422, "Invalid document context")
    fingerprint = hashlib.sha256(data).hexdigest()
    document_key = hashlib.sha256((fingerprint + ":" + document_context).encode()).hexdigest()
    duplicate = db.scalar(select(Case).where(Case.tenant == p.tenant, Case.document_key == document_key))
    if duplicate:
        audit(
            db, duplicate, p.sub, "idempotency", "duplicate_document_prevented", {"duplicate_prevented": True}
        )
        db.commit()
        return case_json(duplicate)
    doc_id = str(uuid4())
    folder = settings().data_dir / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_id}.{kind}"
    path.write_bytes(data)
    c = Case(
        tenant=p.tenant,
        created_by=p.sub,
        kind="intake",
        state=State.INTAKE,
        request_key=request_key,
        document_key=document_key,
        payload={
            "document_path": str(path.resolve()),
            "mime": file.content_type,
            "document_fingerprint": fingerprint,
            "document_context": document_context,
            "provider_mode": settings().provider_mode,
        },
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        path.unlink(missing_ok=True)
        winner = db.scalar(select(Case).where(Case.tenant == p.tenant, Case.document_key == document_key))
        if not winner:
            winner = db.scalar(
                select(Case).where(
                    Case.tenant == p.tenant, Case.created_by == p.sub, Case.request_key == request_key
                )
            )
        if not winner:
            raise HTTPException(409, "Concurrent upload; reload before retrying")
        return case_json(winner)
    enqueue(db, c)
    audit(db, c, p.sub, "transition", "document_uploaded", {"to": State.INTAKE})
    db.commit()
    return case_json(c)


@app.get("/api/cases/{case_id}/document")
def document(case_id: str, p: Auth, db: DB):
    c = accessible(p, db.get(Case, case_id))
    if c.kind != "intake":
        raise HTTPException(404, "Document unavailable")
    return FileResponse(
        c.payload["document_path"], media_type=c.payload["mime"], headers={"Content-Disposition": "inline"}
    )


class Correction(Strict):
    fields: dict[str, str] = Field(max_length=9)
    revision: int


@app.patch("/api/cases/{case_id}/fields")
def correct(case_id: str, body: Correction, p: Auth, db: DB):
    require(p, "pharmacist")
    c = accessible(p, db.get(Case, case_id))
    if (
        c.kind != "intake"
        or c.state not in {State.REVIEW, State.CLARIFICATION}
        or c.revision != body.revision
    ):
        raise HTTPException(409, "Reload the case before editing")
    if not body.fields or any(
        k not in FIELD_NAMES or not v.strip() or len(v) > 500 for k, v in body.fields.items()
    ):
        raise HTTPException(422, "Provide known, nonempty fields")
    fields = {k: dict(v) for k, v in c.payload["extraction"]["fields"].items()}
    changes = [
        {
            "field": k,
            "before": fields[k].get("value"),
            "after": v.strip(),
            "reviewer": p.sub,
            "at": now(),
            "revision": c.revision + 1,
        }
        for k, v in body.fields.items()
    ]
    for k, v in body.fields.items():
        fields[k] = {**fields[k], "value": v.strip(), "issue": None, "confidence": 1}
        audit(db, c, p.sub, "correction", "field_corrected", {"field": k})
    c.payload = {
        **c.payload,
        "extraction": {**c.payload["extraction"], "fields": fields},
        "correction_history": c.payload.get("correction_history", []) + changes,
        "approval": None,
        "corrected_fields": sorted(set(c.payload.get("corrected_fields", [])) | set(body.fields)),
    }
    matches = list(
        db.scalars(
            select(Patient).where(
                Patient.tenant == p.tenant,
                Patient.name == fields["patient_name"]["value"],
                Patient.dob == fields["dob"]["value"],
            )
        )
    )
    if len(matches) != 1:
        c.patient_id = None
        c.action = None
        c.action_hash = None
        c.approved_hash = None
        c.approved_by = None
        c.state = State.CLARIFICATION
    else:
        c.patient_id = matches[0].id
        prepare(c)
        c.state = State.REVIEW
    c.revision += 1
    c.updated_at = now()
    db.commit()
    return case_json(c)


class Approval(Strict):
    action_hash: str
    attested: bool


@app.post("/api/cases/{case_id}/approve")
def approve(case_id: str, body: Approval, p: Auth, db: DB):
    require(p, "pharmacist")
    c = accessible(p, db.get(Case, case_id))
    if (
        c.state != State.REVIEW
        or not c.action
        or body.action_hash != c.action_hash
        or c.action_hash != action_hash(c.action)
        or not body.attested
    ):
        raise HTTPException(409, "Exact current action and pharmacist attestation required")
    fields = c.payload["extraction"]["fields"]
    corrected = c.payload.get("corrected_fields", [])
    if any(
        not fields.get(k, {}).get("value")
        or (
            (fields[k].get("issue") or fields[k]["confidence"] < 0.85 or not fields[k].get("evidence"))
            and k not in corrected
        )
        for k in FIELD_NAMES
    ):
        raise HTTPException(422, "Resolve all missing, uncertain and conflicting fields before approval")
    c.payload = {
        **c.payload,
        "approval": {
            "case_id": c.id,
            "action_hash": c.action_hash,
            "revision": c.revision + 1,
            "reviewer": p.sub,
            "expires_at": now() + settings().approval_seconds,
        },
    }
    c.approved_hash = c.action_hash
    c.approved_by = p.sub
    c.state = State.EXECUTION
    c.revision += 1
    c.updated_at = now()
    enqueue(db, c)
    audit(
        db,
        c,
        p.sub,
        "approval",
        "pharmacist_approved_exact_action",
        {"action_hash": c.action_hash, "to": c.state},
    )
    db.commit()
    return case_json(c)


@app.post("/api/cases/{case_id}/cancel")
def cancel(case_id: str, p: Auth, db: DB):
    c = accessible(p, db.get(Case, case_id))
    if c.state in TERMINAL or c.state in {State.EXECUTION, State.VERIFICATION}:
        raise HTTPException(409, "Execution may already be recorded; reconcile before any further action")
    c.state = State.CANCELLED
    c.revision += 1
    c.updated_at = now()
    audit(db, c, p.sub, "transition", "cancelled", {"to": c.state})
    db.commit()
    return case_json(c)


class Resolution(Strict):
    revision: int
    patient_id: str | None = None
    reason: str = Field(min_length=5, max_length=500)


@app.get("/api/cases/{case_id}/candidates")
def candidates(case_id: str, p: Auth, db: DB):
    require(p, "pharmacist")
    c = accessible(p, db.get(Case, case_id))
    if c.kind != "intake" or c.state != State.CLARIFICATION:
        raise HTTPException(409, "Patient clarification is not active")
    f = c.payload.get("extraction", {}).get("fields", {})
    return [
        {"id": x.id, "name": x.name, "dob": x.dob}
        for x in db.scalars(
            select(Patient).where(
                Patient.tenant == p.tenant,
                Patient.name == f.get("patient_name", {}).get("value"),
                Patient.dob == f.get("dob", {}).get("value"),
            )
        )
    ]


@app.post("/api/cases/{case_id}/resolve-patient")
def resolve_patient(case_id: str, body: Resolution, p: Auth, db: DB):
    options = candidates(case_id, p, db)
    c = accessible(p, db.get(Case, case_id))
    if c.revision != body.revision or body.patient_id not in {r["id"] for r in options}:
        raise HTTPException(409, "Select a current matching patient after reviewing evidence")
    c.patient_id = body.patient_id
    c.payload = {**c.payload, "patient_resolution": {"reviewer": p.sub, "reason": body.reason, "at": now()}}
    prepare(c)
    c.state = State.REVIEW
    c.revision += 1
    c.updated_at = now()
    audit(db, c, p.sub, "review", "ambiguous_patient_resolved", {"to": c.state})
    db.commit()
    return case_json(c)


@app.post("/api/cases/{case_id}/reject")
def reject(case_id: str, body: Resolution, p: Auth, db: DB):
    require(p, "pharmacist")
    c = accessible(p, db.get(Case, case_id))
    if c.revision != body.revision or c.state not in {State.REVIEW, State.CLARIFICATION}:
        raise HTTPException(409, "Only a current unexecuted draft can be rejected")
    c.state = State.REJECTED
    c.approved_by = c.approved_hash = None
    c.payload = {**c.payload, "approval": None, "rejection": {"reason": body.reason, "reviewer": p.sub}}
    c.revision += 1
    c.updated_at = now()
    audit(db, c, p.sub, "review", "pharmacist_rejected", {"to": c.state})
    db.commit()
    return case_json(c)


@app.post("/api/cases/{case_id}/retry")
def retry(case_id: str, p: Auth, db: DB):
    require(p, "pharmacist", "administrator")
    c = accessible(p, db.get(Case, case_id))
    job = db.get(Job, c.id)
    if c.state != State.ESCALATED or not job or job.status != "dead" or not c.action:
        raise HTTPException(409, "Only exhausted transaction jobs can be retried")
    c.state = State.EXECUTION
    c.revision += 1
    c.updated_at = now()
    enqueue(db, c)
    audit(db, c, p.sub, "transition", "human_retry_requested", {"to": c.state})
    db.commit()
    return case_json(c)


@app.post("/api/voice/transcribe")
async def transcribe(p: Auth, file: UploadFile = File(...)):
    require(p, "patient")
    rate_limit(p.tenant + ":" + p.sub, "voice", 12)
    usage_context.set({"tenant": p.tenant, "actor": p.sub})
    data = await file.read(MAX_BYTES + 1)
    try:
        validate_audio(data, file.content_type)
    except ValueError:
        raise HTTPException(422, "Use recorded audio up to 10 MB")
    try:
        return await asyncio.to_thread(
            Provider().transcribe,
            data,
            "recording."
            + {
                "audio/webm": "webm",
                "audio/wav": "wav",
                "audio/mpeg": "mp3",
                "audio/mp4": "mp4",
                "audio/ogg": "ogg",
            }[file.content_type],
        )
    except BudgetExceeded:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(502, "Transcription unavailable; retry recording or use text") from None


class Speech(Strict):
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/voice/speak")
async def speak(body: Speech, p: Auth):
    require(p, "patient")
    rate_limit(p.tenant + ":" + p.sub, "speech", 20)
    usage_context.set({"tenant": p.tenant, "actor": p.sub})
    if settings().provider_mode == "fixture":
        return {"mode": "fixture", "text": body.text}
    return Response(await asyncio.to_thread(Provider().speak, body.text), media_type="audio/mpeg")


@app.get("/api/metrics")
def metrics(p: Auth, db: DB):
    require(p, "staff", "pharmacist", "administrator")
    rows = [
        c
        for c in db.scalars(select(Case).where(Case.tenant == p.tenant))
        if c.payload.get("usage", {}).get("mode", settings().provider_mode) == settings().provider_mode
    ]
    events = list(
        db.scalars(select(Event).where(Event.tenant == p.tenant, Event.case_id.in_([c.id for c in rows])))
    )
    ids = {c.id for c in rows}
    jobs = list(db.scalars(select(Job).where(Job.case_id.in_(ids)))) if ids else []
    measures = {}

    def metric(name, selected, value=None, unit="cases"):
        selected = list(selected)
        measures[name] = {
            "value": len(selected) if value is None else value,
            "case_ids": list(dict.fromkeys(selected)),
            "unit": unit,
        }

    metric("completed", [c.id for c in rows if c.state == State.COMPLETED])
    metric(
        "completion_rate",
        [c.id for c in rows],
        sum(c.state == State.COMPLETED for c in rows) / max(1, len(rows)),
        "fraction of all cases",
    )
    metric(
        "escalation_rate",
        [c.id for c in rows],
        sum(c.state == State.ESCALATED for c in rows) / max(1, len(rows)),
        "fraction of all cases",
    )
    for field in FIELD_NAMES:
        metric(
            "corrections_" + field,
            [e.case_id for e in events if e.category == "correction" and e.evidence.get("field") == field],
            unit="fields",
        )
    for agent in ["intake", "execution", "verification"]:
        stages = [e for e in events if e.category == "stage" and e.evidence.get("agent") == agent]
        metric(
            "mean_" + agent + "_latency",
            [e.case_id for e in stages],
            sum(e.duration_ms for e in stages) / max(1, len(stages)),
            "ms",
        )
    waiting = [c for c in rows if c.state == State.REVIEW]
    metric(
        "review_wait_seconds",
        [c.id for c in waiting],
        max([now() - c.updated_at for c in waiting], default=0),
        "seconds (oldest)",
    )
    retries = [e for e in events if e.category == "failure"]
    metric("retry_failures", [e.case_id for e in retries], len(retries), "attempts")
    tools = [e for e in events if e.category == "tool"]
    metric("tool_calls", [e.case_id for e in tools], len(tools), "calls")
    metric("human_review", [c.id for c in rows if c.kind == "intake"])
    metric("extraction_corrections", [e.case_id for e in events if e.category == "correction"], unit="fields")
    metric(
        "patient_match_failures",
        [e.case_id for e in events if e.name in {"identity_failed", "patient_match_requires_clarification"}],
    )
    metric("failed_actions", [e.case_id for e in events if e.category == "failure"])
    metric("duplicate_prevention", [e.case_id for e in events if e.evidence.get("duplicate_prevented")])
    pending = [j for j in jobs if j.status in {"ready", "running"}]
    metric(
        "oldest_queue_age",
        [j.case_id for j in pending],
        max([max(0, now() - j.available_at) for j in pending], default=0),
        "seconds",
    )
    completed = [c for c in rows if c.state == State.COMPLETED]
    metric(
        "mean_completion_latency",
        [c.id for c in completed],
        sum(c.updated_at - c.created_at for c in completed) / max(1, len(completed)),
        "seconds",
    )
    usage = [(c.id, c.payload.get("usage", {})) for c in rows]
    metric(
        "model_tokens",
        [c for c, u in usage],
        sum(u.get("tokens_in", 0) + u.get("tokens_out", 0) for _, u in usage),
        "tokens",
    )
    cost = sum(u.get("estimated_cost_usd", 0) for _, u in usage)
    metric(
        "estimated_cost_per_completed", [c for c, u in usage], cost / max(1, len(completed)), "USD estimate"
    )
    alerts = []
    stalled = [
        c.id
        for c in rows
        if c.state not in TERMINAL and now() - c.updated_at > settings().alert_stall_seconds
    ]
    if stalled:
        alerts.append({"name": "Stalled workflows", "case_ids": stalled})
    failed = [j.case_id for j in jobs if j.attempts >= settings().alert_failure_count]
    if failed:
        alerts.append({"name": "Repeated failures", "case_ids": failed})
    expired = [j.case_id for j in jobs if j.status == "running" and j.lease_until < now()]
    if expired:
        alerts.append({"name": "Worker lease expired: check worker health and restart", "case_ids": expired})
    exhausted = [c.id for c in rows if c.tool_calls >= settings().max_tool_calls]
    if exhausted:
        alerts.append({"name": "Tool budget exhausted: pharmacist review required", "case_ids": exhausted})
    ledger = list(db.scalars(select(ProviderUsage).where(ProviderUsage.tenant == p.tenant)))
    provider_failures = [u for u in ledger if u.status != "completed" and now() - u.created_at < 300]
    if len(provider_failures) >= settings().alert_failure_count:
        alerts.append(
            {
                "name": "Repeated provider failures: check credentials, service and budget",
                "case_ids": list({u.case_id for u in provider_failures if u.case_id}),
            }
        )
    budget = db.get(Budget, "global")
    if settings().provider_mode == "live" and (
        settings().live_total_budget_usd <= 0
        or (
            budget
            and budget.reserved_usd + settings().live_call_reservation_usd > settings().live_total_budget_usd
        )
    ):
        alerts.append({"name": "Live reservation budget exhausted or unconfigured", "case_ids": []})
    coverage = {
        component: {
            "calls": len([u for u in ledger if u.component == component]),
            "estimated_usd": sum(u.estimated_usd or 0 for u in ledger if u.component == component),
            "unpriced_calls": len(
                [u for u in ledger if u.component == component and u.estimated_usd is None]
            ),
        }
        for component in ["responses", "embeddings", "transcription", "speech"]
    }
    ledger_cost = sum(u.estimated_usd or 0 for u in ledger)
    if settings().provider_mode == "live":
        measures["estimated_cost_per_completed"]["value"] = (
            ledger_cost / len(completed)
            if completed and ledger and all(u.estimated_usd is not None for u in ledger)
            else "unavailable"
        )
    if ledger_cost > settings().alert_cost_usd and cost <= settings().alert_cost_usd:
        alerts.append(
            {
                "name": "Estimated provider cost threshold",
                "case_ids": list({u.case_id for u in ledger if u.case_id}),
            }
        )
    metric(
        "provider_estimated_charges",
        [u.case_id for u in ledger if u.case_id],
        ledger_cost,
        "USD (priced calls only)",
    )
    if cost > settings().alert_cost_usd:
        alerts.append({"name": "Estimated cost threshold", "case_ids": [c for c, u in usage]})
    return {
        "mode": settings().provider_mode,
        "synthetic": True,
        "measures": measures,
        "alerts": alerts,
        "cost_coverage": coverage,
        "pricing_version": settings().pricing_version,
        "cost_note": "Fixture calls cost zero. Live charges use versioned operator rates; unpriced calls remain unavailable, never assumed free. Embedding/audio/judge usage is in the provider ledger. Reservations are conservative operator limits, not invoices.",
    }


@app.get("/api/evaluations")
def evaluations(p: Auth, db: DB):
    require(p, "staff", "pharmacist", "administrator")
    return [
        {"id": e.id, "created_at": e.created_at, "report": e.report}
        for e in db.scalars(
            select(Evaluation).where(Evaluation.tenant == p.tenant).order_by(Evaluation.created_at.desc())
        )
    ]


class Label(Strict):
    scenario_id: str
    score: int = Field(ge=1, le=5)
    note: str = Field(max_length=1000)


@app.post("/api/evaluations/{evaluation_id}/labels")
def label(evaluation_id: str, body: Label, p: Auth, db: DB):
    require(p, "pharmacist", "administrator")
    e = db.get(Evaluation, evaluation_id)
    if (
        not e
        or e.tenant != p.tenant
        or body.scenario_id not in {r.get("sample_id", r["scenario_id"]) for r in e.report.get("rows", [])}
    ):
        raise HTTPException(404, "Evaluation scenario unavailable")
    row = db.scalar(
        select(JudgeLabel).where(
            JudgeLabel.evaluation_id == e.id,
            JudgeLabel.scenario_id == body.scenario_id,
            JudgeLabel.reviewer == p.sub,
        )
    )
    if not row:
        row = JudgeLabel(
            evaluation_id=e.id, scenario_id=body.scenario_id, reviewer=p.sub, score=body.score, note=body.note
        )
        db.add(row)
    else:
        row.score = body.score
        row.note = body.note
    db.commit()
    return {"saved": True}


@app.get("/api/evaluations/{evaluation_id}/agreement")
def agreement(evaluation_id: str, p: Auth, db: DB):
    require(p, "staff", "pharmacist", "administrator")
    e = db.get(Evaluation, evaluation_id)
    if not e or e.tenant != p.tenant:
        raise HTTPException(404, "Unavailable")
    labels = list(db.scalars(select(JudgeLabel).where(JudgeLabel.evaluation_id == e.id)))
    judge = {
        r.get("sample_id", r["scenario_id"]): r.get("judge_score")
        for r in e.report.get("rows", [])
        if r.get("judge_score") is not None
    }
    pairs = [(item.score, judge[item.scenario_id]) for item in labels if item.scenario_id in judge]
    return {
        "calibration": "pending" if not pairs else "observed_small_sample",
        "paired_labels": len(pairs),
        "exact_agreement": sum(a == b for a, b in pairs) / len(pairs) if pairs else None,
        "mean_absolute_error": sum(abs(a - b) for a, b in pairs) / len(pairs) if pairs else None,
    }


frontend = Path(__file__).resolve().parents[1] / "frontend/dist"
if frontend.exists():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
