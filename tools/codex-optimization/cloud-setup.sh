#!/usr/bin/env bash
# Optional Codex Cloud setup command: offline validation, no global mutations.
set -euo pipefail
optimization_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python "${optimization_root}/tools/codex-optimization/verify_setup.py"
