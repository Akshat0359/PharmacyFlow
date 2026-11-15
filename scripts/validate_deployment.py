"""Static checks always run; Compose validation runs only with Docker installed."""

from pathlib import Path
import json
import shutil
import subprocess
import yaml

root = Path(__file__).resolve().parents[1]
compose = yaml.safe_load((root / "compose.yaml").read_text())
expected = {"api", "worker", "mock", "mcp", "db", "otel", "jaeger", "migrate"}
assert expected <= compose["services"].keys()
assert "volumes" in compose and len(compose["volumes"]) >= 4
for name in ["api", "mock", "db"]:
    assert "healthcheck" in compose["services"][name]
assert compose["services"]["worker"]["depends_on"]["mock"]["condition"] == "service_healthy"
for file in [
    "deploy/otel.yaml",
    "deploy/jaeger.yaml",
    "deploy/compose.cloud.yaml",
    ".github/workflows/ci.yml",
]:
    assert yaml.safe_load((root / file).read_text())
report = {
    "static_config": "passed",
    "compose_config": "not_run_docker_unavailable",
    "live_cloud": "not_run_requires_host_dns_and_paid_resources",
    "postgres_acceptance": "not_run_requires_docker_or_test_postgresql",
    "migration_preservation": "see_tests_test_migrations",
}
cloud = yaml.safe_load((root / "deploy/compose.cloud.yaml").read_text())
for name in ["api", "migrate", "mock", "mcp", "worker"]:
    assert cloud["services"][name]["environment"]["DEMO_MODE"] == "false"
    assert cloud["services"][name]["environment"]["ALLOW_FAULT_INJECTION"] == "false"
for name in ["api", "worker", "db", "jaeger", "otel"]:
    assert "mem_limit" in cloud["services"][name]
if shutil.which("docker"):
    r = subprocess.run(["docker", "compose", "config", "--quiet"], cwd=root, capture_output=True, text=True)
    report["compose_config"] = "passed" if r.returncode == 0 else "failed"
    if r.returncode:
        report["error"] = r.stderr
(root / "reports").mkdir(exist_ok=True)
(root / "reports/deployment.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if report["compose_config"] == "failed":
    raise SystemExit(1)
