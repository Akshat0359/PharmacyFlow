"""Install npm's pinned CLI under this folder when the host only supplies Node."""

from pathlib import Path
import tarfile
import urllib.request

root = Path(__file__).resolve().parents[1]
dest = root / ".tools/npm"
dest.mkdir(parents=True, exist_ok=True)
archive = dest / "npm.tgz"
urllib.request.urlretrieve("https://registry.npmjs.org/npm/-/npm-11.7.0.tgz", archive)
with tarfile.open(archive) as tar:
    tar.extractall(dest, filter="data")
print("Local npm CLI: .tools/npm/package/bin/npm-cli.js")
