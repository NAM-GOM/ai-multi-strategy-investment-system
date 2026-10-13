"""Read-only, offline integrity and configuration checks for Cloud setup."""

import hashlib
import json
import re
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root / "tools/codex-optimization/sources.lock.json").read_text())
    if lock["automatic_third_party_activation"]:
        raise ValueError("Automatic third-party activation must remain disabled")
    for source in lock["sources"]:
        if not re.fullmatch(r"[a-f0-9]{40}", source["reviewed_commit"]):
            raise ValueError("Invalid source revision")
        if source["active"]:
            raise ValueError("Unverified third-party source must not be active")
        for path, expected in source.get("staged_files", {}).items():
            resolved = (root / path).resolve()
            resolved.relative_to(root)
            actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"Integrity mismatch: {path}")
    directory = root / "tools/codex-optimization/available-skills"
    names = []
    for path in sorted(directory.glob("*/SKILL.md")):
        content = path.read_text()
        if not content.startswith("---\n") or "\n---\n" not in content[4:]:
            raise ValueError(f"Missing skill frontmatter: {path}")
        match = re.search(r"^name: ([a-z0-9-]+)$", content, re.MULTILINE)
        if not match or not (path.parent / "LICENSE").is_file():
            raise ValueError(f"Missing skill name or license: {path}")
        names.append(match[1])
    if len(names) != len(set(names)):
        raise ValueError("Duplicate staged skill names")
    skill = root / ".agents/skills/codex-efficient-workflow/SKILL.md"
    if "Use only when explicitly asked" not in skill.read_text():
        raise ValueError("Portable skill must be opt-in")
    agents = (root / "AGENTS.md").read_text()
    for requirement in ["Universal Codex Efficiency Rules", "STRICT", "required", "security"]:
        if requirement not in agents:
            raise ValueError(f"Missing existing safety rule: {requirement}")
    print(
        json.dumps(
            {
                "integrity": "PASS",
                "staged_skills": names,
                "cloud_host_skill_discovery": "UNVERIFIED",
                "automatic_mcp_hooks_observers": "DISABLED",
            }
        )
    )


if __name__ == "__main__":
    main()
