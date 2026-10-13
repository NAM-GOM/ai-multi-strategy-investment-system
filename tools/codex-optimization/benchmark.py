"""Offline synthetic workflow checks; never claims model or vendor performance."""

import argparse
import ast
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FIELDS = [
    "test",
    "variant",
    "status",
    "repetitions",
    "median_elapsed_ms",
    "tool_calls",
    "read_bytes",
    "output_bytes",
    "changed_files",
    "checks_passed",
    "checks_total",
    "input_tokens",
    "output_tokens",
    "detail",
]
REPEATS = 5


def command(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.decode()[-2000:])
    return result.stdout + result.stderr


def sample(operation):
    timings = []
    result = None
    for _ in range(REPEATS):
        start = time.perf_counter()
        result = operation()
        timings.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(timings), 3), result


def row(test, variant, status="PASS", **values):
    result = dict.fromkeys(FIELDS, "UNKNOWN")
    result.update(test=test, variant=variant, status=status, **values)
    return result


def main(output):
    rows = []
    with tempfile.TemporaryDirectory(prefix="codex-opt-fixture-") as temp:
        root = Path(temp)
        source = root / "src"
        source.mkdir()
        target = source / "limits.py"
        original = (
            "class RiskGate:\n    pass\n\ndef clamp_limit(value):\n    return min(value, 100)\n"
        )
        target.write_text(original)
        for index in range(50):
            (source / f"unrelated_{index}.py").write_text(
                "# RiskGate and clamp_limit are referenced in documentation.\n"
                + f"def unrelated_{index}(value):\n    return value\n" * 10
            )
        truth = {"RiskGate", "clamp_limit"}
        assert {
            n.name
            for n in ast.parse(original).body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef))
        } == truth

        def broad_search():
            return command(["rg", "-n", "RiskGate|clamp_limit", "src"], root)

        def targeted_search():
            return command(["rg", "-n", "^(class RiskGate|def clamp_limit)\\b", "src"], root)

        for variant, operation in [
            ("baseline-rg", broad_search),
            ("portable-targeted-rg", targeted_search),
        ]:
            elapsed, data = sample(operation)
            text = data.decode()
            found = {name for name in truth if f"{name}(" in text or f"{name}:" in text}
            assert found == truth
            rows.append(
                row(
                    "TEST-A",
                    variant,
                    repetitions=REPEATS,
                    median_elapsed_ms=elapsed,
                    tool_calls=1,
                    output_bytes=len(data),
                    checks_passed=2,
                    checks_total=2,
                    detail="Definition recall 2/2; broad output also has 50 comment hits",
                )
            )
        rows.append(
            row(
                "TEST-A",
                "Serena",
                "BLOCKED",
                repetitions=0,
                detail="Install failed; no symbolic search or MCP comparison",
            )
        )

        error = "ERROR E042 request_id=fixture-42 cause=timeout recovery=retry-exhausted"
        log = "INFO health=ok elapsed_ms=4\n" * 10000 + error + "\n"
        data = [{"id": i, "status": "ok", "value": i} for i in range(3000)]
        data[42] = {
            "id": 42,
            "status": "error",
            "error": "E042",
            "cause": "timeout",
            "recovery": "retry-exhausted",
        }
        payload = json.dumps(data)
        assert all(
            marker in log and marker in payload for marker in ["E042", "timeout", "retry-exhausted"]
        )
        rows.append(
            row(
                "TEST-B",
                "uncompressed-log-json",
                repetitions=1,
                read_bytes=len(log.encode()) + len(payload.encode()),
                output_bytes=len(log.encode()) + len(payload.encode()),
                checks_passed=3,
                checks_total=3,
                detail="Synthetic raw fixture includes error/cause/recovery",
            )
        )
        rows.append(
            row(
                "TEST-B",
                "Headroom",
                "BLOCKED",
                repetitions=0,
                detail="Install failed; compression size/loss/latency unverified",
            )
        )

        tests = root / "tests"
        tests.mkdir()
        (tests / "test_limits.py").write_text(
            "import unittest\nfrom src.limits import clamp_limit\n"
            "class LimitTests(unittest.TestCase):\n"
            "    def test_negative(self): self.assertEqual(clamp_limit(-1), 0)\n"
            "    def test_upper(self): self.assertEqual(clamp_limit(150), 100)\n"
            "    def test_middle(self): self.assertEqual(clamp_limit(42), 42)\n"
        )
        (tests / "test_other.py").write_text(
            "import unittest\nclass OtherTests(unittest.TestCase):\n"
            + "\n".join(
                f"    def test_{i}(self): self.assertEqual({i}+1, {i + 1})" for i in range(100)
            )
            + "\n"
        )

        def modify(focused):
            target.write_text(original)
            start = time.perf_counter()
            reads = [target] if focused else sorted(source.glob("*.py"))
            read_bytes = sum(len(p.read_bytes()) for p in reads)
            target.write_text(original.replace("min(value, 100)", "max(0, min(value, 100))"))
            check_output = b""
            calls = 1  # Explicit fixture read operation, not Codex tool usage.
            if focused:
                check_output += command(
                    [
                        sys.executable,
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        "tests",
                        "-p",
                        "test_limits.py",
                        "-q",
                    ],
                    root,
                )
                calls += 1
            check_output += command(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], root
            )
            calls += 1
            changed = sum(p.read_text() != original for p in [target])
            assert changed == 1 and "Ran 103 tests" in check_output.decode()
            return (time.perf_counter() - start) * 1000, read_bytes, len(check_output), calls

        for variant, focused in [("baseline-full-read", False), ("portable-focused", True)]:
            samples = [modify(focused) for _ in range(REPEATS)]
            rows.append(
                row(
                    "TEST-C",
                    variant,
                    repetitions=REPEATS,
                    median_elapsed_ms=round(statistics.median(s[0] for s in samples), 3),
                    read_bytes=samples[-1][1],
                    output_bytes=samples[-1][2],
                    tool_calls=samples[-1][3],
                    changed_files=1,
                    checks_passed=103,
                    checks_total=103,
                    detail="Same patch; full 103 tests once per run; focused variant adds 3 tests",
                )
            )

        facts = {
            "goal": "clamp negative inputs",
            "file": "src/limits.py",
            "base": "synthetic-v1",
            "checks": "103/103",
            "blocker": "network",
        }
        history = root / "history.json"
        checkpoint = root / "checkpoint.json"
        history.write_text(json.dumps({"events": ["unrelated decision"] * 3000, "facts": facts}))
        checkpoint.write_text(json.dumps(facts))

        for variant, path in [("baseline-history", history), ("portable-checkpoint", checkpoint)]:

            def recall():
                content = path.read_bytes()
                decoded = json.loads(content)
                recovered = decoded["facts"] if "facts" in decoded else decoded
                assert recovered == facts and recovered["base"] == "synthetic-v1"
                return content

            elapsed, content = sample(recall)
            rows.append(
                row(
                    "TEST-D",
                    variant,
                    repetitions=REPEATS,
                    median_elapsed_ms=elapsed,
                    tool_calls=1,
                    read_bytes=len(content),
                    checks_passed=5,
                    checks_total=5,
                    detail="Deterministic file recall; no Cloud session or model inference",
                )
            )
        rows.append(
            row(
                "TEST-D",
                "Claude-Mem",
                "SECURITY_HOLD",
                repetitions=0,
                detail="Observer disabled; provider/egress and persistence unverified",
            )
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "csv": str(output),
                "sha256": digest,
                "rows": len(rows),
                "scope": "synthetic local workflows; actual model tokens UNKNOWN",
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
