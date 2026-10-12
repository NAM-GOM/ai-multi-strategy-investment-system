#!/usr/bin/env bash
set -euo pipefail
release_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$release_dir"
exec "$release_dir/.venv/bin/python" -m trading_system.runtime.cli preflight "$@"
