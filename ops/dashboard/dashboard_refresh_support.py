"""Inline read-only dashboard source/freshness support; no exchange client or writes."""

import json as _refresh_json
import time as _refresh_time
from datetime import datetime as _RefreshDatetime
from pathlib import Path as _RefreshPath

_REFRESH_STATE = _RefreshPath("/var/lib/CryptoAutoTrading/state")
_REFRESH_CONTINUOUS = {
    "market": _REFRESH_STATE / "continuous-01/market/market.sqlite",
    "observer": _REFRESH_STATE / "continuous-01/observer/observer.sqlite",
}
_REFRESH_SERVICES = {
    "collector": "crypto-market-collector.service",
    "observer": "crypto-strategy-observer.service",
    "bridge": "crypto-testnet-bridge.service",
    "account": "crypto-testnet-account-sync.service",
}
_REFRESH_HEALTH = {
    "collector": "market/health.json",
    "observer": "observer/health.json",
    "bridge": "bridge/health.json",
    "account": "account/health.json",
}


def _continuous_refresh_account(data, now):
    evidence = data["evidence"]
    path = _REFRESH_STATE / "continuous-01/account/latest-account.json"
    evidence["accountDataSource"] = "E01_JOURNAL_SNAPSHOT"
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        pass  # The validation below marks inaccessible snapshots as invalid.
    try:
        if path.resolve() != path or path.stat().st_size > 1_000_000:
            raise ValueError
        snapshot = _refresh_json.loads(path.read_text(encoding="utf-8"))
        if (
            snapshot["schemaVersion"] != 1
            or snapshot["mode"] != "READ_ONLY_TESTNET_ACCOUNT_SYNC"
            or snapshot["execution_enabled"] is not False
            or snapshot["real_journal_modified"] is not False
            or snapshot["account_session_id"] != data.get("session", {}).get("id")
            or type(snapshot["balance_timestamp_ms"]) is not int
            or snapshot["balance_timestamp_ms"] > now * 1000
        ):
            raise ValueError
        balances = snapshot["balances"]
        if not isinstance(balances, list) or not 1 <= len(balances) <= 1000:
            raise ValueError
        for row in balances:
            if not isinstance(row, dict) or not all(
                isinstance(row.get(k), str) for k in ("asset", "free", "locked", "time")
            ):
                raise ValueError
            if _continuous_refresh_age(row["time"], now) is None:
                raise ValueError
            if not all(0 <= float(row[k]) < float("inf") for k in ("free", "locked")):
                raise ValueError
        data["balances"] = balances
        evidence["balancesKnown"] = True
        evidence["dataTimes"]["balances"] = _RefreshDatetime.fromtimestamp(
            snapshot["balance_timestamp_ms"] / 1000, __import__("datetime").timezone.utc
        ).isoformat()
        evidence["accountDataSource"] = "GET_RECONCILED_ACCOUNT_SNAPSHOT"
        evidence["accountSnapshotPath"] = str(path)
        evidence["orderDataSource"] = "E01_JOURNAL_RECORDED_HISTORY"
        # Complete valuation is not inferred merely from refreshed balances.
        data["account"]["equity"] = None
        data["account"]["initialEquity"] = None
        data["equityHistory"] = []
        evidence["freshValuation"] = False
    except OSError, ValueError, KeyError, TypeError, OverflowError:
        data["balances"] = []
        evidence["balancesKnown"] = False
        evidence["dataTimes"]["balances"] = None
        evidence["accountDataSource"] = "ACCOUNT_SNAPSHOT_INVALID"
        evidence["freshValuation"] = False
        evidence.setdefault("notes", []).append("계좌 스냅샷 오류 또는 세션 변경: 최신 잔고 미확인")


def _continuous_refresh_select(databases):
    selected, evidence = dict(databases), {}
    # Custom injected sources in offline tests retain their supplied paths.
    for name, current in databases.items():
        kind = "E01_JOURNAL" if name == "testnet" else "EXPLICIT_SOURCE"
        expected = _REFRESH_STATE / f"close-validation-01/{name}.sqlite"
        if name in _REFRESH_CONTINUOUS and current == expected:
            candidate = _REFRESH_CONTINUOUS[name]
            try:
                candidate.lstat()
                selected[name], kind = candidate, "CONTINUOUS"
            except FileNotFoundError:
                kind = "LEGACY_VALIDATION_FALLBACK"
            except OSError:
                # An unreadable continuous source is an error, not permission to
                # present a readable old validation DB as current operational data.
                selected[name], kind = candidate, "CONTINUOUS_ACCESS_ERROR"
        evidence[name] = {"path": str(selected[name]), "kind": kind}
    return selected, evidence


def _continuous_refresh_age(value, now):
    try:
        stamp = _RefreshDatetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return None
        age = now - stamp.timestamp()
        return age if age >= 0 else None
    except TypeError, ValueError, OverflowError:
        return None


def _continuous_refresh_health(role, now):
    target = _REFRESH_STATE / "continuous-01" / _REFRESH_HEALTH[role]
    try:
        if target.resolve() != target or target.stat().st_size > 128_000:
            raise ValueError
        health = _refresh_json.loads(target.read_text(encoding="utf-8"))
        boot = _RefreshPath("/proc/sys/kernel/random/boot_id")
        expected_boot = boot.read_text().strip() if boot.is_file() else None
        age = now - health["timestamp_ms"] / 1000
        state = health["state"]
        if health["role"] != role or health["boot_id"] != expected_boot or age < 0:
            raise ValueError
        if state not in {"STARTING", "READY", "HOLD", "STOPPED", "FAILED"}:
            raise ValueError
        allowed = 90 if role == "account" else 30
        return {"state": state if age <= allowed else "HOLD", "ageSeconds": age}
    except OSError, ValueError, KeyError, TypeError:
        return {"state": "UNKNOWN", "ageSeconds": None}


def _continuous_refresh_enrich(data, sources, include_host):
    now = _refresh_time.time()
    evidence = data.setdefault("evidence", {})
    _continuous_refresh_account(data, now)
    evidence["sources"] = sources
    freshness = {}
    for name in ("market", "observer", "balances"):
        age = _continuous_refresh_age(evidence.get("dataTimes", {}).get(name), now)
        allowed = 14_460 if name == "observer" else 30
        status = "UNKNOWN" if age is None else "FRESH" if age <= allowed else "STALE"
        freshness[name] = {"ageSeconds": age, "state": status, "allowedAgeSeconds": allowed}
    evidence["freshness"] = freshness
    evidence["apiHeartbeatIsDataHeartbeat"] = False
    if any(s["kind"] == "LEGACY_VALIDATION_FALLBACK" for s in sources.values()):
        evidence.setdefault("notes", []).append(
            "상시 운영 DB가 없어 과거 24H 검증 기록을 표시합니다"
        )
    if freshness["balances"]["state"] != "FRESH":
        evidence.setdefault("notes", []).append(
            "계좌 잔고 갱신 중단: GET 전용 계좌 동기화 서비스 필요"
        )
    if include_host:
        healths = {role: _continuous_refresh_health(role, now) for role in _REFRESH_SERVICES}
        evidence["runtimeHealth"] = healths
        for role, service in _REFRESH_SERVICES.items():
            active = data.get("services", {}).get(service, "unknown")
            state = "STOPPED" if active in ("inactive", "failed") else healths[role]["state"]
            if role == "account":
                data["server"]["accountSync"] = state
            else:
                data["server"][role] = state
    return data
