"""Database-backed limits shared by API replicas; no raw IP/user names persisted."""

import hashlib
from sqlalchemy import update, delete
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from .db import session
from .models import RateWindow, now


def rate_limit(identity, bucket, limit, seconds=60):
    period = int(now() // seconds)
    key = hashlib.sha256(f"{identity}:{bucket}:{period}".encode()).hexdigest()
    with session() as db:
        db.execute(delete(RateWindow).where(RateWindow.expires_at < now()))
        if not db.get(RateWindow, key):
            db.add(RateWindow(key=key, count=0, expires_at=(period + 1) * seconds))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        result = db.execute(
            update(RateWindow)
            .where(RateWindow.key == key, RateWindow.count < limit)
            .values(count=RateWindow.count + 1)
        )
        if not result.rowcount:
            raise HTTPException(429, "Request rate exceeded; wait one minute before retrying")
        db.commit()
