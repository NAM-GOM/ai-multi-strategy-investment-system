"""Durable local command spool; only the leased executor writes the E01 journal."""

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from trading_system.observer.model import digest
from trading_system.persistence.records import now_ms
from trading_system.persistence.store import PersistenceError, WriterLease
from trading_system.runtime.common import atomic_json
from trading_system.testnet.client import TestnetError

COMMANDS = frozenset(
    {
        "allocate",
        "phase-a",
        "order-test",
        "on",
        "off",
        "kill",
        "cancel",
        "recover",
        "reset-kill",
        "bind",
    }
)


class Control:
    def __init__(self, directory, *, clock=now_ms):
        self.root, self.clock = Path(directory).resolve(), clock
        self.mode_path = self.root / "mode.json"
        self.requests = self.root / "requests"
        self.stop_path = self.root / "emergency-stop.json"

    @contextmanager
    def lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 5
        while True:
            try:
                lease = WriterLease(self.root / "control")
                break
            except PersistenceError:
                if time.monotonic() >= deadline:
                    raise TestnetError("E02_CONTROL_BUSY") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            lease.close()

    def mode(self):
        if not self.mode_path.exists():
            return {"enabled": False, "epoch": None, "activation_token": None}
        try:
            value = json.loads(self.mode_path.read_text())
            if type(value["enabled"]) is not bool:
                raise ValueError
            return value
        except OSError, KeyError, TypeError, ValueError:
            raise TestnetError("E02_CONTROL_CORRUPT") from None

    def off(self):
        with self.lock():
            atomic_json(
                self.mode_path,
                {"enabled": False, "epoch": uuid.uuid4().hex, "activation_token": None},
            )

    def killed(self):
        return self.stop_path.exists()

    def enqueue(self, command, *, token=None, client_id=None):
        if command not in COMMANDS:
            raise TestnetError("E02_UNSUPPORTED_COMMAND")
        # Disable new POSTs immediately, even while the executor is inside a cycle.
        if command in {"off", "kill"}:
            self.off()
        if command == "kill":
            with self.lock():
                atomic_json(self.stop_path, {"kill": True, "time_ms": self.clock()})
        health = self.root / "health.json"
        instance = json.loads(health.read_text())["instance"] if health.exists() else None
        if not instance and command not in {"off", "kill"}:
            raise TestnetError("E02_EXECUTOR_NOT_STARTED")
        request = {
            "id": uuid.uuid4().hex,
            "command": command,
            "created_ms": self.clock(),
            "token": token,
            "client_id": client_id,
            "runtime_instance": instance,
        }
        atomic_json(self.requests / (request["id"] + ".json"), request)
        return {
            "state": "REQUESTED",
            "id": request["id"],
            "command": command,
            "execution_enabled": self.mode()["enabled"],
        }

    def pending(self):
        if not self.requests.exists():
            return []
        return sorted(self.requests.glob("*.json"), key=lambda p: p.stat().st_mtime_ns)

    def finish(self, path, result):
        request = json.loads(path.read_text())
        atomic_json(self.root / "responses" / path.name, {"request": request, "result": result})
        path.unlink()
        if os.name != "nt":
            descriptor = os.open(self.requests, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def authorize(self, evidence, expected_epoch):
        with self.lock():
            if self.mode()["epoch"] != expected_epoch or self.killed():
                raise TestnetError("E02_CONTROL_CHANGED")
            atomic_json(
                self.mode_path,
                {"enabled": True, "epoch": uuid.uuid4().hex, "activation_token": digest(evidence)},
            )
