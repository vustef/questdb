#!/usr/bin/env python3

import argparse
import json
import math
import os
import re
import statistics
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TEST_SOURCE = REPO / "core/src/test/java/io/questdb/test/griffin/ClickBenchTest.java"
BASE_URL = os.environ.get("CLICKBENCH_URL", "http://127.0.0.1:9000")


def load_queries() -> dict[str, str]:
    source = TEST_SOURCE.read_text()
    matches = re.findall(
        r'new TestCase\(\s*"(Q\d+)",\s*"((?:\\.|[^"\\])*)",',
        source,
    )
    queries = {name: json.loads(f'"{raw}"') for name, raw in matches}
    if len(queries) != 43:
        raise RuntimeError(f"Expected 43 queries in {TEST_SOURCE}, found {len(queries)}")
    return queries


def execute(sql: str, timeout: int) -> tuple[dict, int, int]:
    url = f"{BASE_URL}/exec?{urlencode({'query': sql, 'timings': 'true'})}"
    started = time.perf_counter_ns()
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        payload = json.load(error)
    wall_ns = time.perf_counter_ns() - started
    if "error" in payload:
        raise RuntimeError(
            f"QuestDB error at SQL position {payload.get('position')}: {payload['error']}"
        )
    execute_ns = int(payload.get("timings", {}).get("execute", 0))
    if execute_ns <= 0:
        raise RuntimeError("QuestDB response did not contain timings.execute")
    return payload, execute_ns, wall_ns


def percentile_95(values: list[int]) -> int:
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]


def milliseconds(value: int) -> float:
    return value / 1_000_000


def benchmark(
    name: str,
    sql: str,
    warmups: int,
    runs: int,
    timeout: int,
    show_result: bool,
) -> bool:
    print(f"\n{name}: {sql}")
    try:
        for index in range(warmups):
            _, execute_ns, wall_ns = execute(sql, timeout)
            print(
                f"  warmup {index + 1:>2}: "
                f"server={milliseconds(execute_ns):9.3f} ms  "
                f"wall={milliseconds(wall_ns):9.3f} ms"
            )

        server_times = []
        wall_times = []
        first_payload = None
        for index in range(runs):
            payload, execute_ns, wall_ns = execute(sql, timeout)
            first_payload = first_payload or payload
            server_times.append(execute_ns)
            wall_times.append(wall_ns)
            print(
                f"  run    {index + 1:>2}: "
                f"server={milliseconds(execute_ns):9.3f} ms  "
                f"wall={milliseconds(wall_ns):9.3f} ms"
            )

        print(
            "  server summary: "
            f"min={milliseconds(min(server_times)):.3f} ms  "
            f"median={milliseconds(int(statistics.median(server_times))):.3f} ms  "
            f"mean={milliseconds(int(statistics.mean(server_times))):.3f} ms  "
            f"p95={milliseconds(percentile_95(server_times)):.3f} ms"
        )
        print(
            "  wall summary:   "
            f"min={milliseconds(min(wall_times)):.3f} ms  "
            f"median={milliseconds(int(statistics.median(wall_times))):.3f} ms"
        )
        if show_result and first_payload is not None:
            print(f"  result: {json.dumps(first_payload.get('dataset', []))}")
        return True
    except Exception as error:
        print(f"  FAILED: {error}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark canonical queries parsed directly from ClickBenchTest.java. "
            "QuestDB's server-side timings.execute is the primary metric."
        )
    )
    parser.add_argument(
        "selection",
        nargs="?",
        default="q10",
        help="q10 (default), all, or another query number such as q28",
    )
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-result", action="store_true")
    parser.add_argument(
        "--table",
        default="hits",
        help="table to query (default: hits)",
    )
    args = parser.parse_args()

    if args.warmups < 0 or args.runs < 1:
        parser.error("--warmups must be >= 0 and --runs must be >= 1")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.table):
        parser.error("--table must be an unquoted SQL identifier")

    queries = load_queries()
    selection = args.selection.upper()
    if selection == "ALL":
        selected = sorted(queries.items(), key=lambda item: int(item[0][1:]))
    else:
        if selection.isdigit():
            selection = f"Q{selection}"
        if selection not in queries:
            parser.error(f"unknown query {args.selection!r}; expected q0..q42 or all")
        selected = [(selection, queries[selection])]

    if args.table != "hits":
        selected = [
            (name, re.sub(r"\bhits\b", args.table, sql))
            for name, sql in selected
        ]

    failures = 0
    for name, sql in selected:
        if not benchmark(
            name,
            sql,
            args.warmups,
            args.runs,
            args.timeout,
            show_result=not args.no_result,
        ):
            failures += 1

    if failures:
        raise SystemExit(f"{failures} query benchmark(s) failed")


if __name__ == "__main__":
    main()
