"""Local process supervisor. Ctrl+C gracefully stops only its own child processes."""

import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".tools/browsers"))
    subprocess.run([sys.executable, "scripts/setup.py"], check=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "pharmacyflow.seed"], check=True)
    if not (ROOT / "fixtures/documents/manifest.json").exists():
        subprocess.run([sys.executable, "scripts/generate_fixtures.py"], check=True)
    processes = []
    logs = []
    commands = {
        "api": ["uvicorn", "pharmacyflow.api:app", "--host", "127.0.0.1", "--port", "8000"],
        "mock": ["uvicorn", "pharmacyflow.mock_app:app", "--host", "127.0.0.1", "--port", "8001"],
        "mcp": ["pharmacyflow.mcp_server"],
        "worker": ["pharmacyflow.worker"],
    }
    try:
        for name, args in commands.items():
            log = open(ROOT / "data" / (name + ".log"), "a", encoding="utf8")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", *args],
                    cwd=ROOT,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            )
        print("PharmacyFlow: http://127.0.0.1:8000 | Mock pharmacy: http://127.0.0.1:8001", flush=True)
        print(
            "Synthetic demo credentials: role username + DEMO_PASSWORD in .env. Ctrl+C stops services.",
            flush=True,
        )
        while True:
            for name, process in zip(commands, processes):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} stopped; inspect data/{name}.log")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
