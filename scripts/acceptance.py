"""Owns isolated real services and kills/restarts only its own worker. No paid credentials."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait_until(fn, seconds=60):
    start = time.monotonic()
    last = None
    while time.monotonic() - start < seconds:
        try:
            result = fn()
            if result:
                return result
        except (httpx.HTTPError, KeyError) as exc:
            last = type(exc).__name__
        time.sleep(0.2)
    raise TimeoutError(f"Acceptance condition not reached within {seconds}s; last={last}")


def main():
    from pharmacyflow.config import settings

    original_url = settings().database_url
    run = ROOT / "data" / ("acceptance-" + uuid4().hex[:8])
    run.mkdir(parents=True)
    app_url = "sqlite:///" + str(run / "app.db")
    mock_db_url = "sqlite:///" + str(run / "mock.db")
    checkpoint_url = "sqlite:///" + str(run / "checkpoints.db")
    if "--postgres" in sys.argv:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url

        base = make_url(original_url)
        if base.get_backend_name() != "postgresql":
            raise SystemExit("--postgres requires DATABASE_URL pointing to the test PostgreSQL server")
        # New databases only; never repurpose an existing application database.
        suffix = uuid4().hex[:12]
        names = ["pf_acceptance_" + suffix, "pf_mock_" + suffix]
        with create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT").connect() as conn:
            for name in names:
                conn.execute(text('CREATE DATABASE "' + name + '"'))
        app_url = base.set(database=names[0]).render_as_string(hide_password=False)
        mock_db_url = base.set(database=names[1]).render_as_string(hide_password=False)
        checkpoint_url = base.set(database=names[0], drivername="postgresql").render_as_string(
            hide_password=False
        )
    os.environ.update(
        DATABASE_URL=app_url,
        MOCK_DATABASE_URL=mock_db_url,
        CHECKPOINT_URL=checkpoint_url,
        DATA_DIR=str(run),
        MOCK_URL="http://127.0.0.1:8011",
        MCP_URL="http://127.0.0.1:8012/mcp",
        MCP_PORT="8012",
        PROVIDER_MODE="fixture",
        QUEUE_LEASE_SECONDS="4",
        ALLOW_FAULT_INJECTION="true",
        DEMO_MODE="true",
    )
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tools/browsers"))
    settings.cache_clear()
    from pharmacyflow.db import engine, session
    from pharmacyflow.models import Case, Event, MockRequest
    from sqlalchemy import select, func

    engine.cache_clear()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "pharmacyflow.seed"], cwd=ROOT, check=True)
    processes = []
    logs = []
    report = {
        "mode": "fixture",
        "level": 2 if "--postgres" in sys.argv else "real_transport_sqlite",
        "database": "postgresql" if "--postgres" in sys.argv else "sqlite",
        "transport": "real HTTP + MCP Streamable HTTP + Chromium UI + process restart",
        "checks": {},
        "cases": [],
    }

    def start(name, args):
        f = open(run / (name + ".log"), "a", encoding="utf8")
        logs.append(f)
        p = subprocess.Popen(
            [sys.executable, "-m", *args],
            cwd=ROOT,
            stdout=f,
            stderr=f,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        processes.append(p)
        return p

    try:
        start("api", ["uvicorn", "pharmacyflow.api:app", "--host", "127.0.0.1", "--port", "8010"])
        start("mock", ["uvicorn", "pharmacyflow.mock_app:app", "--host", "127.0.0.1", "--port", "8011"])
        start("mcp", ["pharmacyflow.mcp_server"])
        worker = start("worker", ["pharmacyflow.worker"])
        client = httpx.Client(base_url="http://127.0.0.1:8010", timeout=15)
        wait_until(lambda: client.get("/ready").status_code == 200)
        assert client.get("/ready").json()["database"] == report["database"]
        wait_until(lambda: httpx.get("http://127.0.0.1:8011/health").status_code == 200)

        def login(role):
            r = client.post("/api/login", json={"username": role, "password": settings().demo_password})
            r.raise_for_status()
            return {"Authorization": "Bearer " + r.json()["token"]}

        patient = login("patient")
        pharmacist = login("pharmacist")
        staff = login("staff")

        def get(cid, h=pharmacist):
            r = client.get("/api/cases/" + cid, headers=h)
            r.raise_for_status()
            return r.json()

        def post(path, data, h=patient):
            r = client.post("/api" + path, json=data, headers=h)
            r.raise_for_status()
            return r.json()

        c = post(
            "/refills",
            {
                "message": "I would like my fictional refill",
                "request_key": str(uuid4()),
                "fault": "timeout_after_write",
            },
        )
        cid = c["id"]
        report["cases"].append(cid)
        post("/cases/" + cid + "/identity", {"dob": "1988-04-12", "code": "246810", "confirmed": True})
        post("/cases/" + cid + "/select", {"prescription_id": "rx-001", "confirmed": True})
        failed = wait_until(
            lambda: next((e for e in get(cid)["events"] if e["category"] == "failure"), None), 90
        )
        # Abruptly terminate this owned worker, then use a new OS process and existing durable state.
        worker.kill()
        worker.wait(timeout=10)
        with session(settings().mock_database_url) as db:
            before = db.scalar(
                select(func.count()).select_from(MockRequest).where(MockRequest.idempotency_key == cid)
            )
        assert before == 1, "The write must succeed before the lost response"
        worker = start("worker-restarted", ["pharmacyflow.worker"])
        result = wait_until(lambda: x if (x := get(cid))["state"] == "completed" else None, 90)
        with session(settings().mock_database_url) as db:
            after = db.scalar(
                select(func.count()).select_from(MockRequest).where(MockRequest.idempotency_key == cid)
            )
        assert after == 1
        assert any(e["evidence"].get("duplicate_prevented") for e in result["events"])
        assert result["result"]["status"] == "recorded_for_pharmacist"
        report["checks"]["timeout_restart_reconciliation"] = {
            "passed": True,
            "writes_before_restart": before,
            "writes_after_restart": after,
            "failure_type": failed["evidence"]["error_type"],
            "case_id": cid,
        }
        print("PASS: timeout after write, worker restart, reconciliation, no duplicate.", flush=True)

        async def mcp_boundaries():
            from pharmacyflow.mcp_client import Tools
            from pharmacyflow.security import Principal, token

            with session() as db:
                row = db.get(Case, cid)
                tools = Tools(row, "verification")
            saved = await tools.call("request_status")
            assert saved["request"]["id"] == result["result"]["id"]
            for tenant, role, agent, seconds in [
                ("other", "worker", "verification", 60),
                ("demo", "patient", "verification", 60),
                ("demo", "worker", "intake", 60),
                ("demo", "worker", "verification", -1),
            ]:
                tools.auth = token(
                    Principal(sub="worker", tenant=tenant, role=role, case_id=cid, agent=agent),
                    "mcp",
                    seconds=seconds,
                )
                try:
                    await tools.call("request_status")
                except RuntimeError:
                    continue
                raise AssertionError("MCP accepted an invalid scope")

        asyncio.run(mcp_boundaries())
        report["checks"]["real_mcp_scope_rejections"] = {"passed": True, "cases": 4}

        def upload(name):
            r = client.post(
                "/api/intakes",
                headers=staff,
                files={"file": (name, (ROOT / "fixtures/documents" / name).read_bytes(), "image/png")},
                data={"request_key": str(uuid4()), "document_context": run.name},
            )
            r.raise_for_status()
            return r.json()["id"]

        scan = upload("scanned-uncertain.png")
        report["cases"].append(scan)
        review = wait_until(lambda: x if (x := get(scan))["state"] == "review" else None)
        assert review["payload"]["extraction"]["fields"]["strength"]["confidence"] < 0.85
        denied = client.post(
            "/api/cases/" + scan + "/approve",
            headers=pharmacist,
            json={"action_hash": review["action_hash"], "attested": True},
        )
        assert denied.status_code == 422
        r = client.patch(
            "/api/cases/" + scan + "/fields",
            headers=pharmacist,
            json={"fields": {"strength": "10 demo-units"}, "revision": review["revision"]},
        )
        r.raise_for_status()
        post(
            "/cases/" + scan + "/approve",
            {"action_hash": r.json()["action_hash"], "attested": True},
            pharmacist,
        )
        complete = wait_until(lambda: x if (x := get(scan))["state"] == "completed" else None, 90)
        assert any(e["name"] == "browser_saved_and_read_back" for e in complete["events"])
        report["checks"]["scan_correction_approval_visible_ui"] = {"passed": True, "case_id": scan}
        print(
            "PASS: scanned evidence, blocked premature approval, correction, browser save/readback.",
            flush=True,
        )
        evil = upload("adversarial.png")
        report["cases"].append(evil)
        evilcase = wait_until(lambda: x if (x := get(evil))["state"] == "review" else None)
        assert "untrusted_instruction_detected" in evilcase["payload"]["extraction"]["warnings"]
        assert not any(e["name"] == "prepare_transaction" for e in evilcase["events"])
        with session(settings().mock_database_url) as db:
            assert (
                db.scalar(
                    select(func.count()).select_from(MockRequest).where(MockRequest.idempotency_key == evil)
                )
                == 0
            )
        report["checks"]["adversarial_document_no_unauthorized_tools"] = {"passed": True, "case_id": evil}
        print("PASS: adversarial document remained untrusted data; no unauthorized transaction.", flush=True)
        # Generate new content at runtime; it cannot exist in the known-hash fixture manifest.
        import pymupdf as fitz
        import hashlib

        fields = {
            "patient_name": "Avery Morgan",
            "dob": "1988-04-12",
            "prescriber": "Dr Synthetic New",
            "medication": "UnseenDemo (fictional)",
            "strength": "8 demo-units",
            "directions": "One synthetic unit daily",
            "quantity": "41",
            "date": "2026-11-13",
            "refills": "1",
        }
        with fitz.open() as document:
            document.new_page().insert_text(
                (35, 40), "SYNTHETIC UNSEEN INTAKE\n" + "\n".join(f"{k}: {v}" for k, v in fields.items())
            )
            raw = document.tobytes()
        assert hashlib.sha256(raw).hexdigest() not in json.loads(
            (ROOT / "fixtures/documents/manifest.json").read_text()
        )
        r = client.post(
            "/api/intakes",
            headers=staff,
            files={"file": ("new.pdf", raw, "application/pdf")},
            data={"request_key": str(uuid4())},
        )
        r.raise_for_status()
        fresh = r.json()["id"]
        reviewed = wait_until(lambda: x if (x := get(fresh))["state"] == "review" else None)
        assert reviewed["payload"]["extraction"]["fields"]["medication"]["evidence"]
        post(
            f"/cases/{fresh}/approve", {"action_hash": reviewed["action_hash"], "attested": True}, pharmacist
        )
        wait_until(lambda: get(fresh)["state"] == "completed", 90)
        report["checks"]["unseen_content_intake"] = {
            "passed": True,
            "case_id": fresh,
            "mode": "fixture_content_text_parser",
        }
        report["cases"].append(fresh)
        from pharmacyflow.models import Prescription

        for fault in [
            "expired_session",
            "changed_selector",
            "slow_page",
            "missing_element",
            "incorrect_patient",
            "browser_crash",
        ]:
            rxid = "rx-" + fault
            with session() as db:
                db.add(
                    Prescription(
                        id=rxid,
                        tenant="demo",
                        patient_id="pat-001",
                        medication="FaultTest (fictional)",
                        strength="1 demo-unit",
                        refills=1,
                    )
                )
                db.commit()
            faulty = post("/refills", {"message": "refill", "request_key": str(uuid4()), "fault": fault})[
                "id"
            ]
            post("/cases/" + faulty + "/identity", {"dob": "1988-04-12", "code": "246810", "confirmed": True})
            post("/cases/" + faulty + "/select", {"prescription_id": rxid, "confirmed": True})
            stopped = wait_until(lambda: x if (x := get(faulty))["state"] == "escalated" else None, 90)
            assert len([e for e in stopped["events"] if e["category"] == "failure"]) == 3
            with session(settings().mock_database_url) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(MockRequest)
                        .where(MockRequest.idempotency_key == faulty)
                    )
                    == 0
                )
            report["checks"][fault] = {"passed": True, "case_id": faulty, "bounded_attempts": 3, "writes": 0}
            report["cases"].append(faulty)
        print("PASS: expired UI sessions and changed selectors stop after bounded retries.", flush=True)
        # Real browser coverage of role login, queue, evidence drawer, and patient interface.
        asyncio.run(browser_checks(settings().demo_password, run))
        report["checks"]["dashboard_browser"] = {"passed": True, "screenshot": str(run / "dashboard.png")}
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        for f in logs:
            f.close()
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports/acceptance.json").write_text(json.dumps(report, indent=2))
        # Preserve the actual acceptance cases for dashboard inspection.
        try:
            with session(original_url) as target, session() as source:
                for cls in [Case, Event]:
                    for item in source.scalars(select(cls)):
                        target.merge(item)
                target.commit()
        except Exception as exc:
            report["dashboard_import_error"] = type(exc).__name__
            report["passed"] = False
            (ROOT / "reports/acceptance.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


async def browser_checks(password, run):
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
        )
        page = await browser.new_page(viewport={"width": 1440, "height": 1050}, permissions=["microphone"])
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto("http://127.0.0.1:8010")
        await page.get_by_label("Demo password").fill(password)
        await page.get_by_role("button", name="Enter workspace").click()
        await page.get_by_role("heading", name="Your pharmacy, in flow.").wait_for()
        await expect(page.locator(".stat strong").first).not_to_have_text("—")
        await page.screenshot(path=str(run / "dashboard.png"), full_page=True)
        await page.get_by_role("row").nth(1).click()
        await page.get_by_role("heading", name="Case timeline").wait_for()
        await page.get_by_role("button", name="Close case").click()
        await page.get_by_role("button", name="Sign out").click()
        await page.get_by_role("heading", name="Open your workspace").wait_for()
        await page.get_by_role("combobox").select_option("patient")
        await page.get_by_label("Demo password").fill(password)
        await page.get_by_role("button", name="Enter workspace").click()
        await page.get_by_role("heading", name="Let’s take the next step.").wait_for()
        await page.get_by_role("button", name="Use microphone").click()
        await page.get_by_role("button", name="Stop recording").wait_for()
        await page.wait_for_timeout(600)  # Collect a nonempty synthetic microphone audio segment.
        await page.get_by_role("button", name="Stop recording").click()
        await page.get_by_text(
            "Deterministic simulated transcription; audio is not interpreted.", exact=True
        ).wait_for()
        await page.get_by_role("button", name="Start refill").click()
        await page.get_by_label("Date of birth", exact=True).fill("1988-04-12")
        await page.get_by_label("Demo verification code", exact=True).fill("246810")
        await page.get_by_label("I confirm these identifiers, including any voice transcription.").check()
        await page.get_by_role("button", name="Verify identity", exact=True).click()
        await page.get_by_role("heading", name="Confirm the prescription").wait_for()
        await page.get_by_role("combobox").select_option("rx-001")
        await page.get_by_label("This is the prescription I am requesting.").check()
        await page.get_by_role("button", name="Record refill request", exact=True).click()
        await page.get_by_text("Your request is recorded.", exact=True).wait_for(timeout=30000)
        await page.screenshot(path=str(run / "patient.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        for element in ["main", ".content", ".patient-grid", ".conversation"]:
            for matched in await page.locator(element).all():
                box = await matched.bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391, (
                    "Mobile layout overflows: " + element
                )
        assert not errors, errors
        ledger = await browser.new_page()
        await ledger.goto("http://127.0.0.1:8011")
        await ledger.get_by_label("Password", exact=True).fill(password)
        await ledger.get_by_role("button", name="View saved records").click()
        await ledger.get_by_role("heading", name="Persisted request ledger").wait_for()
        await expect(ledger.get_by_role("cell", name="recorded_for_pharmacist")).to_have_count(3)
        await ledger.screenshot(path=str(run / "mock-pharmacy.png"), full_page=True)
        await browser.close()


if __name__ == "__main__":
    main()
