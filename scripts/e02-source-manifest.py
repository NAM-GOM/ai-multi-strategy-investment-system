"""Create the additive E02 baseline manifest; never edit Frozen sources."""

import hashlib
import json
import subprocess
from pathlib import Path

BASE = "3e37b0b81b05906e1cee858671f67a4c5a719566"
root = Path(__file__).resolve().parents[1]
names = subprocess.check_output(
    ["git", "ls-tree", "-r", "--name-only", BASE], cwd=root, text=True
).splitlines()
selected = [
    n
    for n in names
    if n.startswith(("src/", "tests/", "scripts/m05", "ops/systemd/"))
    or n in {"pyproject.toml", "uv.lock", "docs/DEV-M05-source-manifest.json"}
]
result = {"baseline": BASE, "sha256_lf": {}}
for name in selected:
    data = subprocess.check_output(["git", "show", BASE + ":" + name], cwd=root)
    result["sha256_lf"][name] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
(root / "docs/DEV-E02-source-manifest.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps({"baseline": BASE, "protected_files": len(selected)}))
