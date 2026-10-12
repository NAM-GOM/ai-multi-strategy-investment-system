"""Validate unit syntax locally with workspace executable paths; installs nothing."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    tool = shutil.which("systemd-analyze")
    if not tool:
        print(json.dumps({"systemd_syntax": "NOT_TESTED", "reason": "tool unavailable"}))
        return 0
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="m05-unit-verify-") as directory:
        units = []
        for source in sorted((root / "ops/systemd").glob("*.service")):
            target = Path(directory) / source.name
            target.write_text(
                source.read_text().replace("/srv/CryptoAutoTrading/releases/dev-m05", str(root))
            )
            units.append(str(target))
        result = subprocess.run([tool, "verify", *units], capture_output=True, text=True)
        print(
            json.dumps(
                {
                    "systemd_syntax": "PASS" if result.returncode == 0 else "FAIL",
                    "scope": "LOCAL_TRANSFORMED_PATHS_NO_INSTALL_NO_BOOT",
                    "diagnostics": result.stderr,
                }
            )
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
