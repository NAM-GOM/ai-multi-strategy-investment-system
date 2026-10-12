"""Isolated paths, durable health reports, and fail-closed process coordination."""

import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from trading_system.observer.model import canonical
from trading_system.persistence.records import now_ms
from trading_system.testnet.client import TestnetError

STATE_ROOT = Path("/var/lib/CryptoAutoTrading/state/continuous-01")
EXECUTION_PATH = Path("/var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite")


@dataclass(frozen=True)
class RuntimePaths:
    root: Path = STATE_ROOT
    execution: Path = EXECUTION_PATH

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).resolve())
        object.__setattr__(self, "execution", Path(self.execution).resolve())
        paths = (self.market, self.observer, self.execution)
        if self.execution.name != "testnet_execution.sqlite":
            raise TestnetError("DEDICATED_DB_REQUIRED")
        if any("close-validation-01" in p.resolve().parts for p in (self.root, *paths)):
            raise TestnetError("PROTECTED_VALIDATION_PATH")
        if len(set(p.resolve() for p in paths)) != 3 or any(
            a.exists() and b.exists() and a.samefile(b)
            for i, a in enumerate(paths)
            for b in paths[i + 1 :]
        ):
            raise TestnetError("DATABASE_PATH_COLLISION")
        # The preview role must never own/write the real execution directory.
        directories = [
            self.role_dir(role).resolve() for role in ("collector", "observer", "bridge", "account")
        ]
        if len(set(directories)) != len(directories) or any(
            self.execution.is_relative_to(directory) for directory in directories
        ):
            raise TestnetError("EXECUTION_RUNTIME_PATH_COLLISION")

    @property
    def market(self):
        return self.root / "market" / "market.sqlite"

    @property
    def observer(self):
        return self.root / "observer" / "observer.sqlite"

    def role_dir(self, role):
        return (
            self.root
            / {
                "collector": "market",
                "observer": "observer",
                "bridge": "bridge",
                "account": "account",
            }[role]
        )

    def health(self, role):
        return self.role_dir(role) / "health.json"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(canonical(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def boot_id():
    path = Path("/proc/sys/kernel/random/boot_id")
    return path.read_text().strip() if path.is_file() else None


class StatusSink:
    def __init__(self, paths, role, *, clock=now_ms):
        self.paths, self.role, self.clock = paths, role, clock
        self.instance = uuid.uuid4().hex
        self.started = clock()
        self.last = None
        directory = paths.role_dir(role)
        directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.Logger("m05." + self.instance)
        self.handler = RotatingFileHandler(
            directory / "runtime.jsonl", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
        self.logger.addHandler(self.handler)

    def publish(self, state, category=None, *, force=False, **details):
        timestamp = self.clock()
        if (
            not force
            and self.last
            and timestamp - self.last["timestamp_ms"] < 10_000
            and self.last["state"] == state
            and self.last["category"] == category
        ):
            return
        record = {
            "role": self.role,
            "state": state,
            "category": category,
            "timestamp_ms": timestamp,
            "started_ms": self.started,
            "instance": self.instance,
            "pid": os.getpid(),
            "boot_id": boot_id(),
            "execution_enabled": False,
            **details,
        }
        atomic_json(self.paths.health(self.role), record)
        self.logger.warning(canonical(record))
        print(canonical(record), flush=True)
        self.last = record

    def close(self):
        self.handler.close()


def require_health(paths, role, now, *, max_age_ms=30_000):
    try:
        record = json.loads(paths.health(role).read_text(encoding="utf-8"))
        if (
            record["role"] != role
            or record["state"] != "READY"
            or record["boot_id"] != boot_id()
            or not 0 <= now - record["timestamp_ms"] <= max_age_ms
        ):
            raise ValueError
        return record
    except OSError, KeyError, TypeError, ValueError:
        raise TestnetError(role.upper() + "_HEARTBEAT_HOLD") from None


@contextmanager
def readonly_database(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise TestnetError("INPUT_DB_MISSING")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        yield db
    finally:
        db.close()


def disabled_environment():
    for key in ("BINANCE_TESTNET_TRADING_ENABLED", "BINANCE_TESTNET_AUTOMATED_ENABLED"):
        if os.environ.get(key, "OFF") != "OFF":
            raise TestnetError("RUNTIME_EXECUTION_UNLOCK_DENIED")


def public_environment():
    if any(
        os.environ.get(key) for key in ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET")
    ):
        raise TestnetError("PUBLIC_SERVICE_CREDENTIALS_DENIED")
