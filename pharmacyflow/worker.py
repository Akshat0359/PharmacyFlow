import asyncio
import signal
import time
from uuid import uuid4
from sqlalchemy import select, update, or_
from .db import session
from .config import settings
from .models import Job, Case, State, TERMINAL, now, AgentOutput
from .workflow import durable_graph, transition
from .telemetry import audit, configure
from .leases import lease_owner


def enqueue(db, case):
    job = db.get(Job, case.id)
    if not job:
        db.add(Job(case_id=case.id))
    else:
        job.status = "ready"
        job.available_at = now()
        job.attempts = 0


def claim(owner):
    with session() as db:
        candidate = db.scalar(
            select(Job.case_id)
            .where(
                or_(
                    (Job.status == "ready") & (Job.available_at <= now()),
                    (Job.status == "running") & (Job.lease_until < now()),
                )
            )
            .order_by(Job.available_at)
            .limit(1)
        )
        if not candidate:
            return None
        result = db.execute(
            update(Job)
            .where(
                Job.case_id == candidate,
                or_(
                    (Job.status == "ready") & (Job.available_at <= now()),
                    (Job.status == "running") & (Job.lease_until < now()),
                ),
            )
            .values(status="running", lease_owner=owner, lease_until=now() + settings().queue_lease_seconds)
        )
        db.commit()
        return candidate if result.rowcount else None


def expire_waiting():
    with session() as db:
        rows = db.scalars(
            select(Case).where(
                Case.state.in_([State.REVIEW, State.IDENTITY, State.CLARIFICATION]),
                Case.created_at < now() - settings().workflow_timeout_seconds,
            )
        )
        for c in rows:
            transition(db, c, AgentOutput(state=State.TIMED_OUT, reason="human_wait_timeout"), "scheduler")
        db.commit()


async def heartbeat(case_id, owner):
    while True:
        await asyncio.sleep(max(1, settings().queue_lease_seconds / 3))
        with session() as db:
            db.execute(
                update(Job)
                .where(
                    Job.case_id == case_id,
                    Job.lease_owner == owner,
                    Job.status == "running",
                    Job.lease_until > now(),
                )
                .values(lease_until=now() + settings().queue_lease_seconds)
            )
            db.commit()


async def run_once(graph, owner):
    owner = owner + ":" + str(uuid4())  # unique fencing token for every claim, including same process
    case_id = claim(owner)
    if not case_id:
        return False
    pulse = asyncio.create_task(heartbeat(case_id, owner))
    ownership = lease_owner.set(owner)
    started = time.perf_counter()
    try:
        with session() as db:
            case = db.get(Case, case_id)
            state = {"case_id": case.id, "state": case.state, "revision": case.revision}
        await graph.ainvoke(state, {"configurable": {"thread_id": case_id}})
        with session() as db:
            job = db.get(Job, case_id)
            case = db.get(Case, case_id)
            if job.lease_owner != owner:
                return True
            waiting = case.state in TERMINAL or case.state in {
                State.REVIEW,
                State.IDENTITY,
                State.CLARIFICATION,
            }
            job.status = "done" if waiting else "ready"
            job.available_at = now()
            job.lease_until = 0
            job.attempts = 0
            audit(
                db,
                case,
                "worker",
                "queue",
                "step_finished",
                {"status": case.state},
                (time.perf_counter() - started) * 1000,
            )
            db.commit()
    except Exception as exc:
        with session() as db:
            job = db.get(Job, case_id)
            case = db.get(Case, case_id)
            if job.lease_owner != owner:
                return True
            job.attempts += 1
            job.last_error = type(exc).__name__
            job.lease_until = 0
            audit(
                db,
                case,
                "worker",
                "failure",
                "step_failed",
                {"error_type": type(exc).__name__, "attempt": job.attempts},
                (time.perf_counter() - started) * 1000,
            )
            if job.attempts >= settings().max_attempts:
                job.status = "dead"
                if case.state not in TERMINAL:
                    transition(
                        db,
                        case,
                        AgentOutput(state=State.ESCALATED, reason="retry_budget_exhausted"),
                        "scheduler",
                    )
            else:
                job.status = "ready"
                job.available_at = now() + 2**job.attempts
            db.commit()
    finally:
        lease_owner.reset(ownership)
        pulse.cancel()
        try:
            await pulse
        except asyncio.CancelledError:
            pass
    return True


async def main():
    settings().validate_runtime()
    configure()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    owner = str(uuid4())
    async with durable_graph() as graph:
        while not stop.is_set():
            expire_waiting()
            if not await run_once(graph, owner):
                await asyncio.sleep(0.4)


if __name__ == "__main__":
    asyncio.run(main())
