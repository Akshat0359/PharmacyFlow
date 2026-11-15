"""Separate mock pharmacy service. Writes happen only via its authenticated HTML form."""

import asyncio
import html
import time
from fastapi import FastAPI, Header, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pwdlib import PasswordHash
from sqlalchemy import select, text, or_
from sqlalchemy.exc import IntegrityError
from .db import session, engine
from .config import settings
from .models import MockRequest, User, Case, Prescription
from .security import decode, action_hash, Principal, token
from .security import valid_approval
from .leases import fence
from .limits import rate_limit

app = FastAPI(title="Mock pharmacy • SYNTHETIC RECORDS")


def claims(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Synthetic pharmacy session required")
    return decode(authorization[7:], "mock")


def serialize(r):
    return (
        {
            "id": r.id,
            "key": r.idempotency_key,
            "action_hash": r.action_hash,
            "status": r.status,
            "patient_id": r.patient_id,
        }
        if r
        else None
    )


@app.get("/health")
def health():
    with engine(settings().mock_database_url).connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "synthetic": True}


@app.get("/api/requests/{key}")
def status(key: str, authorization: str | None = Header(None)):
    c = claims(authorization)
    if key != c["key"]:
        raise HTTPException(403, "Key outside capability")
    with session(settings().mock_database_url) as db:
        r = db.scalar(
            select(MockRequest).where(
                MockRequest.tenant == c["tenant"],
                or_(MockRequest.idempotency_key == key, MockRequest.action_hash == c["action_hash"]),
            )
        )
        return {"request": serialize(r)}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, authorization: str | None = Header(None)):
    if not authorization:
        viewer = request.cookies.get("mock-viewer")
        if viewer:
            try:
                c = decode(viewer, "mock-viewer")
                with session() as db:
                    user = db.get(User, c["sub"])
                    if (
                        not user
                        or user.disabled
                        or (user.demo_account and not settings().demo_mode)
                        or c.get("session_version", 0) != user.session_version
                        or user.tenant != c["tenant"]
                        or user.role not in {"staff", "pharmacist", "administrator"}
                    ):
                        raise HTTPException(403, "Viewer unavailable")
                with session(settings().mock_database_url) as db:
                    records = list(
                        db.scalars(
                            select(MockRequest)
                            .where(MockRequest.tenant == c["tenant"])
                            .order_by(MockRequest.created_at.desc())
                            .limit(250)
                        )
                    )
                rows = "".join(
                    "<tr><td>"
                    + html.escape(r.id[:8])
                    + "</td><td>"
                    + html.escape(r.patient_id)
                    + "</td><td>"
                    + html.escape(r.action.get("prescription_id") or "Intake draft")
                    + "</td><td>"
                    + html.escape(r.status)
                    + "</td></tr>"
                    for r in records
                )
                return viewer_page(
                    "<h2>Persisted request ledger</h2><p>Read-only staff view. Transactions are written by scoped workflow capabilities.</p><table><tr><th>REQUEST</th><th>PATIENT</th><th>PRESCRIPTION</th><th>STATUS</th></tr>"
                    + rows
                    + '</table><form action="/staff-logout" method="post"><button>Sign out</button></form>'
                )
            except HTTPException:
                pass
        return viewer_page(
            '<h2>Open the synthetic record ledger</h2><p>Sign in with a staff, pharmacist or administrator demo account and the local demo password.</p><form method="post" action="/staff-login"><label>Username<input name="username" value="pharmacist" required></label><label>Password<input name="password" type="password" required></label><button>View saved records</button></form>'
        )
    c = claims(authorization)
    action = c["action"]
    if c.get("fault") == "slow_page":
        time.sleep(4)
    displayed_patient = (
        "wrong-synthetic-patient" if c.get("fault") == "incorrect_patient" else action["patient_id"]
    )
    label = "Record request" if c.get("fault") != "changed_selector" else "Save changed transaction"
    return f"""<!doctype html><html><head><title>Mock Pharmacy</title><style>
    body{{font:16px system-ui;background:#eff5f4;color:#163c35;padding:3rem}}main{{max-width:700px;margin:auto;background:white;padding:2rem;border-radius:20px}}label{{display:block;margin:20px 0}}input,button{{font:inherit;padding:12px}}button{{background:#155e50;color:white;border:0;border-radius:8px}}pre{{white-space:pre-wrap}}
    </style></head><body><main><small>SYNTHETIC PHARMACY SYSTEM</small><h1>Transaction workbench</h1>
    <p>Records requests for pharmacist processing. Does not dispense medication.</p>
    <label>Patient<input aria-label="Patient" readonly value="{html.escape(displayed_patient)}"></label>
    <label>Prescription<input aria-label="Prescription" readonly value="{html.escape(action.get("prescription_id") or "New intake draft")}"></label>
    <pre>{html.escape(str(action.get("fields") or action["kind"]))}</pre>
    <form method="post" action="/save"><button type="submit" {"hidden" if c.get("fault") == "missing_element" else ""}>{label}</button></form>
    <h2>Saved request</h2><div id="saved">No request saved in this view.</div></main></body></html>"""


def viewer_page(body):
    return (
        '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Mock Pharmacy • Synthetic ledger</title><style>body{font:15px system-ui;background:#edf3ef;color:#294e3e;padding:4vw}main{max-width:1000px;margin:auto;background:white;padding:35px;border-radius:15px}h1{font-size:30px}p{color:#78917f;line-height:1.7}small{letter-spacing:2px}label{display:block;margin:20px 0}input{display:block;padding:12px;margin-top:7px;border:1px solid #cdddcf;border-radius:6px}button{background:#24614b;border:0;color:white;border-radius:6px;padding:12px 20px;margin-top:15px;cursor:pointer}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:14px 8px;border-bottom:1px solid #e6eee4;font-size:12px}</style></head><body><main><small>PHARMACYFLOW / SEPARATE MOCK APPLICATION</small><h1>Mock Pharmacy</h1><p>SYNTHETIC RECORDS ONLY. No dispensing decisions.</p>'
        + body
        + "</main></body></html>"
    )


@app.post("/staff-login")
def staff_login(username: str = Form(...), password: str = Form(...)):
    rate_limit(username, "mock-login", 12)
    if len(username) > 80 or len(password) > 256:
        raise HTTPException(422, "Invalid credentials")
    with session() as db:
        user = db.scalar(select(User).where(User.username == username))
        if (
            not user
            or user.disabled
            or (user.demo_account and not settings().demo_mode)
            or user.role not in {"staff", "pharmacist", "administrator"}
            or not PasswordHash.recommended().verify(password, user.password_hash)
        ):
            raise HTTPException(401, "Invalid staff credentials")
        cookie = token(
            Principal(sub=user.id, tenant=user.tenant, role=user.role),
            "mock-viewer",
            seconds=900,
            session_version=user.session_version,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "mock-viewer", cookie, httponly=True, samesite="strict", secure=not settings().demo_mode, max_age=900
    )
    return response


@app.post("/staff-logout")
def staff_logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("mock-viewer")
    return response


@app.post("/save", response_class=HTMLResponse)
async def save(request: Request, authorization: str | None = Header(None)):
    c = claims(authorization)
    if not c.get("can_write") or c["action_hash"] != action_hash(c["action"]):
        raise HTTPException(403, "Write capability required")
    # Hold the app job lock through the mock commit, so a superseded worker cannot write.
    with session() as app_db, session(settings().mock_database_url) as db:
        fence(app_db, c.get("case_id"), c.get("lease_owner"), lock=True)
        case = app_db.get(Case, c.get("case_id"))
        if c.get("lease_owner") or not settings().demo_mode:
            if (
                not case
                or case.state != "execution"
                or case.tenant != c["tenant"]
                or case.action_hash != c["action_hash"]
            ):
                raise HTTPException(409, "Case authorization changed")
            if case.kind == "intake" and not valid_approval(app_db, case):
                raise HTTPException(403, "Approval expired or invalid")
            if case.kind == "refill":
                rx = app_db.get(Prescription, case.action["prescription_id"])
                if (
                    not rx
                    or rx.patient_id != case.patient_id
                    or rx.tenant != case.tenant
                    or rx.refills < 1
                    or rx.status != "active"
                    or not case.payload.get("identity_verified")
                    or not case.payload.get("selection_confirmed")
                ):
                    raise HTTPException(403, "Refill authorization changed")
        row = db.scalar(
            select(MockRequest).where(
                MockRequest.tenant == c["tenant"],
                or_(MockRequest.idempotency_key == c["key"], MockRequest.action_hash == c["action_hash"]),
            )
        )
        if row and row.action_hash != c["action_hash"]:
            raise HTTPException(409, "Idempotency conflict")
        inserted = row is None
        if not row:
            row = MockRequest(
                tenant=c["tenant"],
                patient_id=c["action"]["patient_id"],
                idempotency_key=c["key"],
                action_hash=c["action_hash"],
                action=c["action"],
            )
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = db.scalar(
                    select(MockRequest).where(
                        MockRequest.tenant == c["tenant"],
                        or_(
                            MockRequest.idempotency_key == c["key"],
                            MockRequest.action_hash == c["action_hash"],
                        ),
                    )
                )
                if row.action_hash != c["action_hash"]:
                    raise HTTPException(409, "Idempotency conflict")
        result = serialize(row)
    # Commit occurs BEFORE the simulated lost response; the worker must reconcile.
    if inserted and c.get("fault") == "timeout_after_write":
        await asyncio.sleep(8)
    return f"<h1>Saved request</h1><p>SYNTHETIC • Pharmacist processing required</p><output data-testid='receipt' data-hash='{result['action_hash']}' data-request='{result['id']}'>{html.escape(result['status'])}</output>"
