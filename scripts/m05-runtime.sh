#!/usr/bin/env bash
set -euo pipefail
release_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$release_dir"
export PYTHONUNBUFFERED=1
# Use the pinned release interpreter. No environment mutation or dependency fetch at startup.
exec "$release_dir/.venv/bin/python" -m trading_system.runtime.cli "$@"
