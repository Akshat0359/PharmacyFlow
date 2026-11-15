"""Explicitly rebuild trusted policy vectors when changing embedding providers."""

from sqlalchemy import select, text
import json
from .config import settings
from .db import session
from .models import Policy
from .providers import Provider
from .retrieval import release, digest


def main():
    with session() as db:
        policies = list(db.scalars(select(Policy)))
        trusted = {r["id"]: r for version in {p.version for p in policies} for r in release(version)}
        for p in policies:
            original = trusted.get(p.id.split(":", 1)[1])
            if not original or digest(p.text) != digest(original["text"]):
                raise ValueError("Refusing to index modified or unknown policy")
        vectors = Provider().embeddings([p.text for p in policies])
        for p, vector in zip(policies, vectors):
            p.embedding = vector
            if db.bind.dialect.name == "postgresql":
                db.execute(
                    text("UPDATE policies SET vector_embedding=CAST(:v AS vector) WHERE id=:id"),
                    {"v": json.dumps(vector), "id": p.id},
                )
        db.commit()
    (settings().data_dir / "embedding-model.txt").write_text(
        settings().embedding_model if settings().provider_mode == "live" else "fixture-hash64"
    )
    print(f"Indexed {len(vectors)} trusted policy passages in {settings().provider_mode} mode.")


if __name__ == "__main__":
    main()
