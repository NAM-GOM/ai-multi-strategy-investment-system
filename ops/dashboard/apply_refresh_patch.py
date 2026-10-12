"""Apply a reviewed source-only patch to the exact known NUC development API file."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

BASE_SHA = "51affe76a2f0c0b0de255534bdaf2c9430fba2bd07bd187121d2b046bcfcf65c"
API_PATH = Path("/home/nuc-coder/development/nuc-dashboard/dashboard_api.py")
SUPPORT = Path(__file__).with_name("dashboard_refresh_support.py")
SERVICES = (
    "crypto-market-collector.service",
    "crypto-strategy-observer.service",
    "crypto-testnet-bridge.service",
    "crypto-testnet-account-sync.service",
)


def render_patch(source, *, expected_sha=BASE_SHA):
    if hashlib.sha256(source).hexdigest() != expected_sha:
        raise ValueError(
            "Dashboard source differs from reviewed base; preserve edits and re-review"
        )
    text = source.decode("utf-8")
    tree = ast.parse(text)
    snapshot = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "snapshot")
    returns = [
        n
        for n in ast.walk(snapshot)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Name) and n.value.id == "data"
    ]
    if len(returns) != 1:
        raise ValueError("Unsupported snapshot return structure")
    lines = text.splitlines(keepends=True)
    lines.insert(
        returns[0].lineno - 1, "    _continuous_refresh_enrich(data, source_info, include_host)\n"
    )
    text = "".join(lines)
    signature = "def snapshot(databases=DATABASES, include_host=True):\n"
    if text.count(signature) != 1:
        raise ValueError("Unsupported snapshot signature")
    support = SUPPORT.read_text(encoding="utf-8")
    for old_import, alias in (
        ("import json as _refresh_json", "_refresh_json = json"),
        ("import time as _refresh_time", "_refresh_time = time"),
        ("from datetime import datetime as _RefreshDatetime", "_RefreshDatetime = datetime"),
        ("from pathlib import Path as _RefreshPath", "_RefreshPath = Path"),
    ):
        support = support.replace(old_import, alias)
    text = text.replace(
        signature,
        support
        + "\n\n"
        + signature
        + "    databases, source_info = _continuous_refresh_select(databases)\n",
        1,
    )
    tree = ast.parse(text)
    assignment = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "ALLOWED_SERVICES" for t in n.targets)
    )
    old = ast.literal_eval(assignment.value)
    if not isinstance(old, tuple) or any(not isinstance(s, str) for s in old):
        raise ValueError("Unsupported service allowlist")
    lines = text.splitlines(keepends=True)
    lines[assignment.lineno - 1 : assignment.end_lineno] = [
        "ALLOWED_SERVICES = (\n"
        + "".join("    " + repr(service) + ",\n" for service in dict.fromkeys((*old, *SERVICES)))
        + ")\n"
    ]
    text = "".join(lines)
    old_query = (
        "                last = rows(db, 'SELECT symbol,price_text,event_time_ms,received_at_ms "
        "FROM price_snapshots '\n"
        "                            'WHERE (symbol,bucket_start_ms) IN '\n"
        "                            '(SELECT symbol,MAX(bucket_start_ms) FROM price_snapshots "
        "GROUP BY symbol)')"
    )
    if old_query not in text:
        raise ValueError("Unsupported market snapshot query; preserve source and re-review")
    text = text.replace(
        old_query,
        "                last = []\n"
        "                for symbol in sorted(SYMBOLS):\n"
        "                    last.extend(rows(db, 'SELECT symbol,price_text,event_time_ms,'\n"
        "                                     'received_at_ms FROM price_snapshots "
        "WHERE symbol=? '\n"
        "                                     'ORDER BY bucket_start_ms DESC LIMIT 1', (symbol,)))",
        1,
    )
    ast.parse(text)
    return text.encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Hash-bound NUC dashboard development patch")
    parser.add_argument(
        "--apply", action="store_true", help="Update only the fixed development API"
    )
    args = parser.parse_args()
    if API_PATH.resolve() != API_PATH or not API_PATH.is_file():
        raise SystemExit("Fixed development file missing or symlinked")
    original = API_PATH.read_bytes()
    updated = render_patch(original)
    print(
        json.dumps(
            {
                "base_sha256": BASE_SHA,
                "updated_sha256": hashlib.sha256(updated).hexdigest(),
                "target": str(API_PATH),
                "bytes": len(updated),
                "deployment": False,
            }
        )
    )
    if args.apply:
        backup = API_PATH.with_name("dashboard_api.py.pre-refresh-" + BASE_SHA[:12] + ".bak")
        with backup.open("xb") as stream:
            stream.write(original)
        API_PATH.write_bytes(updated)


if __name__ == "__main__":
    main()
