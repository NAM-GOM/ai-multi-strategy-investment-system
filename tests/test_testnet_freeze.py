"""Portable baseline hashes verify DEV-M01–M04 and W03 preservation without Git."""

import hashlib
import json
from pathlib import Path


def test_preexisting_source_and_w03_are_frozen():
    root = Path(__file__).parents[1]
    manifest = json.loads((root / "docs/DEV-E01-freeze-manifest.json").read_text())
    assert manifest["baseline"] == "574eb63597e42724a6450abd0928458ae72c4b88"
    assert manifest["sha256_lf"]
    for relative, expected in manifest["sha256_lf"].items():
        actual = (root / relative).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(actual).hexdigest() == expected, relative
