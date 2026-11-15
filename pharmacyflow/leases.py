"""Fencing shared by queue, graph, MCP and the mock transaction boundary."""

from contextvars import ContextVar
from sqlalchemy import update
from fastapi import HTTPException
from .models import Job, now

lease_owner = ContextVar("lease_owner", default=None)


def fence(db, case_id, owner, *, lock=False):
    job = db.get(Job, case_id)
    if not owner:
        if job and job.status == "running":
            raise HTTPException(409, "Worker lease required")
        return
    if lock:
        # Conditional UPDATE obtains a write lock on SQLite and a row lock on PG.
        result = db.execute(
            update(Job)
            .where(
                Job.case_id == case_id,
                Job.status == "running",
                Job.lease_owner == owner,
                Job.lease_until > now(),
            )
            .values(lease_until=Job.lease_until)
        )
        if not result.rowcount:
            raise HTTPException(409, "Worker lease lost")
    elif not job or job.status != "running" or job.lease_owner != owner or job.lease_until <= now():
        raise HTTPException(409, "Worker lease lost")
