"""Attributable, bounded retention of completed synthetic cases and checkpoints."""

import asyncio
from pathlib import Path
from sqlalchemy import select, delete
from .config import settings
from .db import session
from .models import Case, Event, Job, MockRequest, ProviderUsage, TERMINAL, now
from .workflow import durable_graph


async def purge(actor="administrator:retention", dry_run=True):
    cutoff = now() - settings().retention_days * 86400
    with session() as db:
        rows = list(db.scalars(select(Case).where(Case.updated_at < cutoff, Case.state.in_(TERMINAL))))
        ids = [c.id for c in rows]
        if dry_run:
            return {"dry_run": True, "case_ids": ids, "count": len(ids)}
        for c in rows:
            path = c.payload.get("document_path")
            if path:
                target = Path(path).resolve()
                root = settings().data_dir.resolve()
                if target.is_relative_to(root) and target.is_file():
                    target.unlink()
        async with durable_graph() as graph:
            for cid in ids:
                await graph.checkpointer.adelete_thread(cid)
        db.execute(delete(Event).where(Event.case_id.in_(ids)))
        db.execute(delete(Job).where(Job.case_id.in_(ids)))
        db.execute(delete(Case).where(Case.id.in_(ids)))
        db.execute(delete(ProviderUsage).where(ProviderUsage.created_at < cutoff))
        for c in rows:
            db.add(
                Event(
                    case_id=c.id,
                    tenant=c.tenant,
                    actor=actor,
                    category="retention",
                    name="synthetic_case_purged",
                    evidence={"count": 1},
                )
            )
        db.commit()
    with session(settings().mock_database_url) as db:
        db.execute(delete(MockRequest).where(MockRequest.idempotency_key.in_(ids)))
        db.commit()
    return {"dry_run": False, "count": len(ids)}


if __name__ == "__main__":
    import sys
    import json

    print(json.dumps(asyncio.run(purge(dry_run="--apply" not in sys.argv)), indent=2))
