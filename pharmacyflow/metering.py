"""Persistent conservative call reservations; measured usage is separate from estimated charges."""

from contextvars import ContextVar
from types import SimpleNamespace
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import session
from .models import Budget, ProviderUsage

usage_context = ContextVar("usage_context", default={})


class BudgetExceeded(RuntimeError):
    pass


def reserve():
    cfg = settings()
    amount = cfg.live_call_reservation_usd
    if amount <= 0 or cfg.live_total_budget_usd <= 0:
        raise BudgetExceeded(
            "Configure explicit live total budget and per-call reservation before paid calls"
        )
    context = usage_context.get()
    scopes = [("global", cfg.live_total_budget_usd)]
    if context.get("run_id"):
        scopes.append((context["run_id"], context["run_budget"]))
    for key, _ in scopes:
        with session(settings().metering_database_url or None) as db:
            if not db.get(Budget, key):
                db.add(Budget(id=key, reserved_usd=0))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
    with session(settings().metering_database_url or None) as db:
        for key, limit in scopes:
            result = db.execute(
                update(Budget)
                .where(Budget.id == key, Budget.reserved_usd + amount <= limit)
                .values(reserved_usd=Budget.reserved_usd + amount)
            )
            if not result.rowcount:
                raise BudgetExceeded("Live call reservation budget exhausted")
        db.commit()


def measured(component, result, args):
    cfg = settings()
    raw = getattr(result, "usage", None)
    raw = (
        raw.model_dump()
        if hasattr(raw, "model_dump")
        else vars(raw)
        if hasattr(raw, "__dict__")
        else raw or {}
    )
    usage = {
        k: raw[k]
        for k in ["input_tokens", "output_tokens", "total_tokens", "seconds", "duration"]
        if isinstance(raw.get(k), (int, float))
    }
    cost = None
    if component == "embeddings" and cfg.embedding_usd_per_million > 0 and "total_tokens" in usage:
        cost = usage["total_tokens"] * cfg.embedding_usd_per_million / 1e6
    elif component == "transcription":
        seconds = usage.get("seconds", usage.get("duration"))
        if seconds is not None and cfg.speech_usd_per_minute > 0:
            cost = seconds * cfg.speech_usd_per_minute / 60
    elif component == "speech":
        usage["input_characters"] = len(args.get("input", ""))
        if cfg.tts_usd_per_million_characters > 0:
            cost = usage["input_characters"] * cfg.tts_usd_per_million_characters / 1e6
    elif (
        component == "responses"
        and cfg.model_input_usd_per_million > 0
        and cfg.model_output_usd_per_million > 0
        and "input_tokens" in usage
    ):
        cost = (
            usage["input_tokens"] * cfg.model_input_usd_per_million
            + usage.get("output_tokens", 0) * cfg.model_output_usd_per_million
        ) / 1e6
    return usage, cost


def metered(component, fn):
    def create(**args):
        reserve()
        context = usage_context.get()
        usage, cost, status = {}, None, "failed_or_unknown_charge"
        try:
            result = fn(**args)
            usage, cost = measured(component, result, args)
            status = "completed"
            return result
        finally:
            with session(settings().metering_database_url or None) as db:
                db.add(
                    ProviderUsage(
                        tenant=context.get("tenant", "system"),
                        case_id=context.get("case_id"),
                        actor=context.get("actor", "system"),
                        component=component,
                        model=args.get("model", "unknown"),
                        pricing_version=settings().pricing_version,
                        usage=usage,
                        estimated_usd=cost,
                        status=status,
                    )
                )
                db.commit()

    return SimpleNamespace(create=create)


def guarded(client):
    return SimpleNamespace(
        responses=metered("responses", client.responses.create),
        embeddings=metered("embeddings", client.embeddings.create),
        audio=SimpleNamespace(
            transcriptions=metered("transcription", client.audio.transcriptions.create),
            speech=metered("speech", client.audio.speech.create),
        ),
    )
