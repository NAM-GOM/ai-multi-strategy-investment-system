"""Verify the offline setup gate detects altered third-party skill content."""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_setup_rejects_tampered_skill(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "tools/codex-optimization", tmp_path / "tools/codex-optimization")
    shutil.copytree(root / ".agents/skills", tmp_path / ".agents/skills")
    shutil.copy2(root / "AGENTS.md", tmp_path / "AGENTS.md")
    script = tmp_path / "tools/codex-optimization/verify_setup.py"
    valid = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert valid.returncode == 0
    assert json.loads(valid.stdout)["automatic_mcp_hooks_observers"] == "DISABLED"

    skill = tmp_path / "tools/codex-optimization/available-skills/ponytail/SKILL.md"
    skill.write_text(skill.read_text() + "\nUnexpected additional instruction\n")
    tampered = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert tampered.returncode != 0
    assert "Integrity mismatch" in tampered.stderr
