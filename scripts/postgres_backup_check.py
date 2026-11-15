"""Run on the Compose host. Restore both databases into unique, new databases only.
Quiesce writers first for cross-database consistency; this command never overwrites data.
"""

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4


def main():
    root = Path(__file__).resolve().parents[1]
    report = {"status": "skipped", "reason": "Docker runtime unavailable", "overwrites_existing_data": False}
    if shutil.which("docker"):
        base = ["docker", "compose", "exec", "-T", "db"]
        restored = []
        for source, table in [("pharmacyflow", "cases"), ("mockpharmacy", "mock_requests")]:
            name = "pf_restore_" + uuid4().hex[:12]
            dump = subprocess.run(
                [*base, "pg_dump", "-U", "pharmacy", "-Fc", source], check=True, capture_output=True
            ).stdout
            subprocess.run([*base, "createdb", "-U", "pharmacy", name], check=True)
            subprocess.run([*base, "pg_restore", "-U", "pharmacy", "-d", name], input=dump, check=True)
            query = f"SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY id), '')) FROM {table} t"
            signatures = [
                subprocess.check_output([*base, "psql", "-U", "pharmacy", "-d", db, "-Atc", query])
                .strip()
                .decode()
                for db in [source, name]
            ]
            if signatures[0] != signatures[1]:
                raise RuntimeError("Restored record checksum differs")
            restored.append({"source": source, "restored_database": name, "record_checksum": signatures[0]})
        report = {
            "status": "passed",
            "databases": restored,
            "overwrites_existing_data": False,
        }
    (root / "reports/backup.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
