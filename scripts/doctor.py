"""Portable, secret-free runtime inventory. Does not install or modify host software."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
report = {
    "platform": platform.system(),
    "python_version": platform.python_version(),
    "python_supported": sys.version_info[:2] == (3, 12),
}
for name, arguments in {
    "uv": ["--version"],
    "node": ["--version"],
    "npm": ["--version"],
    "docker": ["version", "--format", "{{.Server.Version}}"],
}.items():
    command = shutil.which(name)
    if not command:
        report[name] = {"available": False}
        continue
    try:
        process = subprocess.run([command, *arguments], capture_output=True, text=True, timeout=15)
        report[name] = {"available": process.returncode == 0, "version": process.stdout.strip()[:100]}
    except (OSError, subprocess.TimeoutExpired):
        report[name] = {"available": False}
report["local_npm"] = (ROOT / ".tools/npm/package/bin/npm-cli.js").exists()
report["local_chromium"] = (ROOT / ".tools/browsers").exists()
(ROOT / "reports/runtime.json").write_text(json.dumps(report, indent=2), encoding="utf8")
print(json.dumps(report, indent=2))
