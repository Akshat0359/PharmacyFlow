import hashlib
import json
import math
import re
from pathlib import Path
from sqlalchemy import select, text
from .models import Policy, now
from .config import settings

CORPUS = Path(__file__).resolve().parents[1] / "fixtures/policies/v1.json"


def release(version="1"):
    if not str(version).isdigit():
        return []
    path = CORPUS.parent / f"v{version}.json"
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else []


def validate_vector(vector):
    if len(vector) != 64 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector):
        raise ValueError(
            "Embedding must contain exactly 64 finite values; dimension changes require an index migration"
        )
    return vector


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def embed(value: str) -> list[float]:
    """Deterministic 64-dimensional feature hashing, clearly distinct from live embeddings."""
    vector = [0.0] * 64
    for word in re.findall(r"[a-z]+", value.lower()):
        h = int(hashlib.sha256(word.encode()).hexdigest()[:8], 16)
        vector[h % 64] += 1
    norm = math.sqrt(sum(v * v for v in vector)) or 1
    return [v / norm for v in vector]


def seed_policies(db, tenant="demo", version="1"):
    rows = release(version)
    if not rows or any(r["version"] != version for r in rows) or len({r["topic"] for r in rows}) != len(rows):
        raise ValueError("Missing or contradictory trusted policy release")
    for row in rows:
        key = f"{tenant}:{row['id']}"
        if db.get(Policy, key):
            continue
        from .providers import Provider

        vector = validate_vector(Provider().embeddings([row["text"]])[0])
        p = Policy(
            id=key,
            tenant=tenant,
            version=row["version"],
            topic=row["topic"],
            text=row["text"],
            digest=digest(row["text"]),
            embedding=vector,
            effective_from=row.get("effective_from", 0),
            effective_until=row.get("effective_until"),
        )
        db.add(p)
        db.flush()
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text("UPDATE policies SET vector_embedding = CAST(:v AS vector) WHERE id=:id"),
                {"v": json.dumps(p.embedding), "id": key},
            )


def retrieve(db, tenant: str, query: str, version="1", limit=3):
    # Filter before ranking/context. Trusted digests are derived from the versioned release corpus,
    # not from a mutable database digest supplied by an attacker.
    trusted = {r["id"]: digest(r["text"]) for r in release(version)}
    policies = list(
        db.scalars(
            select(Policy).where(
                Policy.tenant == tenant,
                Policy.version == version,
                Policy.effective_from <= now(),
                (Policy.effective_until.is_(None)) | (Policy.effective_until > now()),
            )
        )
    )
    rejected = [p.id for p in policies if trusted.get(p.id.split(":", 1)[1]) != digest(p.text)]
    valid = [p for p in policies if p.id not in rejected]
    if not trusted or len(valid) != len(trusted) or rejected:
        return {
            "citations": [],
            "blocked": True,
            "reason": "missing_or_modified_policy",
            "rejected": rejected,
            "engine": db.bind.dialect.name,
        }
    topics = [p.topic for p in valid]
    if len(topics) != len(set(topics)):
        return {
            "citations": [],
            "blocked": True,
            "reason": "contradictory_policy",
            "engine": db.bind.dialect.name,
        }
    # Live vectors require an explicit reindex; a release marker prevents mixing spaces.
    from .providers import Provider

    if settings().provider_mode == "live":
        marker = settings().data_dir / "embedding-model.txt"
        if not marker.exists() or marker.read_text() != settings().embedding_model:
            return {
                "citations": [],
                "blocked": True,
                "reason": "live_policy_reindex_required",
                "engine": db.bind.dialect.name,
            }
    terms = set(re.findall(r"[a-z]+", query.lower())) - {
        "the",
        "a",
        "an",
        "is",
        "are",
        "to",
        "of",
        "for",
        "in",
        "and",
        "or",
        "my",
        "what",
        "how",
        "can",
        "i",
        "me",
        "please",
        "with",
        "do",
        "does",
        "on",
    }
    vocabulary = set(re.findall(r"[a-z]+", " ".join(p.text for p in valid).lower()))
    if not terms & vocabulary:
        return {
            "citations": [],
            "blocked": True,
            "reason": "no_relevant_policy",
            "engine": db.bind.dialect.name,
        }
    qv = validate_vector(Provider().embeddings([query])[0])
    for p in valid:
        validate_vector(p.embedding)
    if db.bind.dialect.name == "postgresql":
        ranks = (
            db.execute(
                text("""SELECT id, ts_rank_cd(search_vector, plainto_tsquery('english', :q)) AS lexical,
            1-(vector_embedding <=> CAST(:v AS vector)) AS semantic
            FROM policies WHERE tenant=:tenant AND version=:version AND effective_from<=:at
            AND (effective_until IS NULL OR effective_until>:at)"""),
                {"q": query, "v": json.dumps(qv), "tenant": tenant, "version": version, "at": now()},
            )
            .mappings()
            .all()
        )
        lexical = sorted(ranks, key=lambda r: r["lexical"], reverse=True)
        semantic = sorted(ranks, key=lambda r: r["semantic"] or 0, reverse=True)
    else:
        terms = set(re.findall(r"[a-z]+", query.lower()))
        lexical = sorted(
            [{"id": p.id, "score": len(terms & set(re.findall(r"[a-z]+", p.text.lower())))} for p in valid],
            key=lambda r: r["score"],
            reverse=True,
        )
        semantic = sorted(
            [{"id": p.id, "score": sum(a * b for a, b in zip(qv, p.embedding))} for p in valid],
            key=lambda r: r["score"],
            reverse=True,
        )
    scores = {}
    for ranking in [lexical, semantic]:
        for rank, item in enumerate(ranking):
            scores[item["id"]] = scores.get(item["id"], 0) + 1 / (60 + rank + 1)
    chosen = sorted(valid, key=lambda p: scores.get(p.id, 0), reverse=True)[:limit]
    return {
        "citations": [
            {
                "document_id": p.id,
                "version": p.version,
                "passage": p.text,
                "score": scores[p.id],
                "digest": p.digest,
                "effective_from": p.effective_from,
                "effective_until": p.effective_until,
            }
            for p in chosen
        ],
        "blocked": False,
        "engine": "postgres_fts_pgvector"
        if db.bind.dialect.name == "postgresql"
        else "sqlite_lexical_hash_fallback",
    }
