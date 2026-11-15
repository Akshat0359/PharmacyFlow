import hashlib
import json
from typing import Annotated
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from .config import settings
from .db import session
from .models import User, Case, now


class Principal(BaseModel):
    sub: str
    tenant: str
    role: str
    patient_id: str | None = None
    case_id: str | None = None
    agent: str | None = None
    lease_owner: str | None = None


def token(p: Principal, audience="app", seconds=3600, **extra):
    return jwt.encode(
        {**p.model_dump(), **extra, "aud": audience, "exp": now() + seconds},
        settings().app_secret,
        algorithm="HS256",
    )


def decode(value: str, audience="app") -> dict:
    try:
        return jwt.decode(value, settings().app_secret, algorithms=["HS256"], audience=audience)
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired or invalid") from None


def authenticate(auth: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())]) -> Principal:
    data = decode(auth.credentials)
    with session() as db:
        user = db.get(User, data["sub"])
        if (
            not user
            or user.tenant != data["tenant"]
            or user.disabled
            or (user.demo_account and not settings().demo_mode)
            or data.get("session_version", 0) != user.session_version
        ):
            raise HTTPException(401, "Account unavailable")
        return Principal(sub=user.id, tenant=user.tenant, role=user.role, patient_id=user.patient_id)


Auth = Annotated[Principal, Depends(authenticate)]


def require(p: Principal, *roles):
    if p.role not in roles:
        raise HTTPException(403, "Role not authorized")


def accessible(p: Principal, case: Case | None) -> Case:
    if not case or case.tenant != p.tenant or (p.role == "patient" and case.patient_id != p.patient_id):
        raise HTTPException(404, "Case unavailable")
    if p.case_id and p.case_id != case.id:
        raise HTTPException(403, "Tool context does not authorize this case")
    return case


def action_hash(action: dict) -> str:
    return hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def valid_approval(db, case):
    approval = case.payload.get("approval") or {}
    reviewer = db.get(User, case.approved_by) if case.approved_by else None
    return bool(
        reviewer
        and reviewer.role == "pharmacist"
        and reviewer.tenant == case.tenant
        and not reviewer.disabled
        and (settings().demo_mode or not reviewer.demo_account)
        and case.approved_hash == case.action_hash
        and approval.get("case_id") == case.id
        and approval.get("action_hash") == case.action_hash
        and approval.get("reviewer") == reviewer.id
        and approval.get("expires_at", 0) > now()
        and approval.get("revision", -1) <= case.revision
    )
