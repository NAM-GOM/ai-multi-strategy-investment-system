"""Offline/source and read-only installation checks. Never an activation command."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from trading_system.observer.audit import source_audit
from trading_system.testnet.client import TestnetError

from .common import disabled_environment, readonly_database

REPOSITORY = Path(__file__).resolve().parents[3]


def protected_sources(root=REPOSITORY):
    manifest = json.loads((root / "docs/DEV-M05-source-manifest.json").read_text())
    for relative, expected in manifest["sha256_lf"].items():
        data = (root / relative).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() != expected:
            raise TestnetError("M05_PROTECTED_SOURCE_MISMATCH")
    return {"baseline": manifest["baseline"], "protected_files": len(manifest["sha256_lf"])}


def preflight(paths, *, host_check=False):
    disabled_environment()
    sources = protected_sources()
    audit = source_audit()
    result = {
        "state": "OFFLINE_PREFLIGHT_PASS",
        "sources": sources,
        "frozen_manifest_hash": audit["manifest_hash"],
        "execution_enabled": False,
        "automated_enabled": False,
        "mode": "DRY_RUN_SIGNAL_ROUTING",
        "network_requests": 0,
        "production_order_path": False,
        "paths": {
            "market": str(paths.market),
            "observer": str(paths.observer),
            "execution_read_only": str(paths.execution),
        },
        "live_acceptance": "NOT_TESTED",
    }
    if host_check:
        if sys.platform != "linux" or sys.version_info[:3] != (3, 14, 7):
            raise TestnetError("NUC_PLATFORM_VERSION_HOLD")
        if shutil.disk_usage(paths.root).free < 2 * 1024**3:
            raise TestnetError("DISK_SPACE_HOLD")
        if not paths.execution.is_file():
            raise TestnetError("EXISTING_E01_LEDGER_REQUIRED")
        with readonly_database(paths.execution) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise TestnetError("EXECUTION_DB_INTEGRITY")
            if not db.execute("SELECT count(*) FROM testnet_sessions").fetchone()[0]:
                raise TestnetError("EXISTING_E01_SESSION_REQUIRED")
            result["existing_order_count"] = db.execute(
                "SELECT count(*) FROM exchange_orders"
            ).fetchone()[0]
            result["existing_fill_count"] = db.execute(
                "SELECT count(*) FROM executions"
            ).fetchone()[0]
        # Refuse broadly writable shared input directories on the installed server.
        for role in ("collector", "observer", "bridge"):
            directory = paths.role_dir(role)
            if directory.stat().st_mode & 0o022:
                raise TestnetError("STATE_DIRECTORY_WRITER_ISOLATION_HOLD")
        result["state"] = "HOST_STATIC_PREFLIGHT_PASS"
        result["service_identity_checks"] = "REQUIRED_AS_EACH_SERVICE_USER"
        result["running_user"] = os.getuid()
    return result
