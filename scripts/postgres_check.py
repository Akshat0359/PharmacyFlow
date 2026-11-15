"""Run inside Compose to verify the actual PostgreSQL vector/FTS and checkpoint backends."""

import asyncio
from sqlalchemy import text
from pharmacyflow.db import session
from pharmacyflow.retrieval import retrieve
from pharmacyflow.workflow import durable_graph

with session() as db:
    assert db.bind.dialect.name == "postgresql"
    assert db.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar() == "vector"
    result = retrieve(db, "demo", "refill identity prescription")
    assert result["engine"] == "postgres_fts_pgvector" and result["citations"]


async def check():
    async with durable_graph() as graph:
        assert graph.checkpointer is not None


asyncio.run(check())
print("PASS PostgreSQL pgvector/FTS retrieval and durable checkpoint initialization")
