from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from pharmacyflow.config import settings
from pharmacyflow.db import session
from pharmacyflow.models import Policy, Budget, ProviderUsage, Job, Case, now
from pharmacyflow.retrieval import retrieve, validate_vector
from pharmacyflow.metering import reserve, BudgetExceeded, metered, usage_context


def test_budget_reservations_are_atomic_and_fail_closed(environment):
    with pytest.raises(BudgetExceeded):
        reserve()
    settings().live_total_budget_usd = 0.2
    settings().live_call_reservation_usd = 0.1

    def attempt(_):
        try:
            reserve()
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 2
    with session() as db:
        assert db.get(Budget, "global").reserved_usd == 0.2


def test_unpriced_calls_not_reported_as_free_and_errors_redacted(environment):
    settings().live_total_budget_usd = 1
    settings().live_call_reservation_usd = 0.1
    ctx = usage_context.set({"tenant": "demo", "actor": "patient"})
    try:
        wrapped = metered(
            "transcription", lambda **kw: SimpleNamespace(text="sensitive transcript", usage=None)
        )
        wrapped.create(model="test", file=b"never log raw audio")

        def fail(**kw):
            raise ValueError("secret raw provider error")

        with pytest.raises(ValueError):
            metered("speech", fail).create(model="test", input="private")
    finally:
        usage_context.reset(ctx)
    with session() as db:
        rows = list(db.scalars(select(ProviderUsage)))
        assert len(rows) == 2 and all(r.estimated_usd is None for r in rows)
        assert "secret" not in str([r.usage for r in rows])
        assert rows[1].status == "failed_or_unknown_charge"


@pytest.mark.parametrize("vector", [[0] * 63, [0] * 65, [float("nan")] * 64])
def test_embedding_shape_and_finite_values(vector):
    with pytest.raises(ValueError):
        validate_vector(vector)


def test_policy_effective_dates_and_negative_queries(environment):
    with session() as db:
        assert retrieve(db, "demo", "weather tomorrow Paris")["reason"] == "no_relevant_policy"
        p = db.get(Policy, "demo:refill-v1")
        p.effective_from = now() + 86400
        db.commit()
        assert retrieve(db, "demo", "refill")["blocked"]


def test_operational_alerts_trigger_and_recover(client, auth, refill):
    c = refill()
    with session() as db:
        row = db.get(Case, c["id"])
        row.updated_at = now() - 1000
        db.add(Job(case_id=c["id"], status="running", lease_owner="dead", lease_until=0))
        db.commit()
    result = client.get("/api/metrics", headers=auth("staff")).json()
    assert any("Worker lease expired" in a["name"] for a in result["alerts"])
    assert any(a["name"] == "Stalled workflows" for a in result["alerts"])
    with session() as db:
        db.get(Case, c["id"]).updated_at = now()
        db.get(Job, c["id"]).status = "done"
        db.commit()
    result = client.get("/api/metrics", headers=auth("staff")).json()
    assert not result["alerts"]


def test_run_budget_is_distinct_from_total(environment):
    settings().live_total_budget_usd = 1
    settings().live_call_reservation_usd = 0.1
    ctx = usage_context.set({"run_id": "live-eval-test", "run_budget": 0.1})
    try:
        reserve()
        with pytest.raises(BudgetExceeded):
            reserve()
    finally:
        usage_context.reset(ctx)
    with session() as db:
        assert db.get(Budget, "global").reserved_usd == 0.1
