#!/usr/bin/env python3

import argparse
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


EXPECTED_BYTES = 14_779_976_446
EXPECTED_ROWS = 99_997_497
HERE = Path(__file__).resolve().parent
DATASET = Path(os.environ.get("CLICKBENCH_IMPORT", HERE / "import")) / "hits.parquet"
BASE_URL = os.environ.get("CLICKBENCH_URL", "http://127.0.0.1:9000")
STAGING_TABLE = "hits_full_load"

# This is the official QuestDB ClickBench schema from:
# https://github.com/ClickHouse/ClickBench/blob/main/questdb/create.sql
OFFICIAL_SCHEMA = """
WatchID LONG,
JavaEnable BYTE,
Title VARCHAR,
GoodEvent BYTE,
EventTime TIMESTAMP,
EventDate TIMESTAMP,
CounterID INT,
ClientIP IPv4,
RegionID INT,
UserID LONG,
CounterClass BYTE,
OS SHORT,
UserAgent SHORT,
URL VARCHAR,
Referer VARCHAR,
IsRefresh BYTE,
RefererCategoryID SHORT,
RefererRegionID INT,
URLCategoryID SHORT,
URLRegionID INT,
ResolutionWidth SHORT,
ResolutionHeight SHORT,
ResolutionDepth SHORT,
FlashMajor BYTE,
FlashMinor BYTE,
FlashMinor2 SYMBOL,
NetMajor BYTE,
NetMinor BYTE,
UserAgentMajor SHORT,
UserAgentMinor SYMBOL,
CookieEnable BYTE,
JavascriptEnable BYTE,
IsMobile BYTE,
MobilePhone SHORT,
MobilePhoneModel SYMBOL,
Params SYMBOL,
IPNetworkID INT,
TraficSourceID INT,
SearchEngineID SHORT,
SearchPhrase VARCHAR,
AdvEngineID SHORT,
IsArtifical BYTE,
WindowClientWidth SHORT,
WindowClientHeight SHORT,
ClientTimeZone SHORT,
ClientEventTime TIMESTAMP,
SilverlightVersion1 BYTE,
SilverlightVersion2 BYTE,
SilverlightVersion3 SHORT,
SilverlightVersion4 BYTE,
PageCharset SYMBOL,
CodeVersion SHORT,
IsLink BYTE,
IsDownload BYTE,
IsNotBounce BYTE,
FUniqID LONG,
OriginalURL VARCHAR,
HID INT,
IsOldCounter BYTE,
IsEvent BYTE,
IsParameter BYTE,
DontCountHits BYTE,
WithHash BYTE,
HitColor CHAR,
LocalEventTime TIMESTAMP,
Age BYTE,
Sex BYTE,
Income BYTE,
Interests SHORT,
Robotness SHORT,
RemoteIP IPv4,
WindowName INT,
OpenerName INT,
HistoryLength SHORT,
BrowserLanguage SYMBOL,
BrowserCountry SYMBOL,
SocialNetwork SYMBOL,
SocialAction SYMBOL,
HTTPError BYTE,
SendTiming INT,
DNSTiming INT,
ConnectTiming INT,
ResponseStartTiming INT,
ResponseEndTiming INT,
FetchTiming INT,
SocialSourceNetworkID SHORT,
SocialSourcePage VARCHAR,
ParamPrice LONG,
ParamOrderID SYMBOL,
ParamCurrency SYMBOL,
ParamCurrencyID SHORT,
OpenstatServiceName SYMBOL,
OpenstatCampaignID SYMBOL,
OpenstatAdID VARCHAR,
OpenstatSourceID SYMBOL,
UTMSource SYMBOL,
UTMMedium SYMBOL,
UTMCampaign SYMBOL,
UTMContent SYMBOL,
UTMTerm SYMBOL,
FromTag SYMBOL,
HasGCLID BYTE,
RefererHash LONG,
URLHash LONG,
CLID INT
"""
SCHEMA = tuple(
    tuple(column.strip().split()) for column in OFFICIAL_SCHEMA.strip().split(",")
)


def source_expression(name: str, target_type: str) -> str:
    if name == "EventDate":
        expression = f"({name}::LONG * 86400000000)::TIMESTAMP"
    elif target_type == "TIMESTAMP":
        expression = f"({name} * 1000000)::TIMESTAMP"
    elif target_type in {"VARCHAR", "SYMBOL", "CHAR"}:
        expression = f"nullif({name}, '')::{target_type}"
    else:
        expression = f"{name}::{target_type}"
    return f"        {expression} AS {name}"


FULL_TABLE_SQL = (
    f"CREATE TABLE {STAGING_TABLE} AS (\n"
    "    SELECT\n"
    + ",\n".join(source_expression(name, target_type) for name, target_type in SCHEMA)
    + "\n    FROM read_parquet('hits.parquet')\n"
    ") TIMESTAMP(EventTime) PARTITION BY DAY;"
)


def execute(sql: str, timeout: int = 3600) -> dict:
    url = f"{BASE_URL}/exec?{urlencode({'query': sql, 'timings': 'true'})}"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        payload = json.load(error)
    if "error" in payload:
        raise RuntimeError(
            f"QuestDB error at SQL position {payload.get('position')}: {payload['error']}"
        )
    return payload


def table_schema(table_name: str) -> list[tuple[str, str]] | None:
    try:
        rows = execute(
            f'select "column", "type" from table_columns(\'{table_name}\')',
            timeout=30,
        )["dataset"]
    except RuntimeError as error:
        if "table does not exist" in str(error):
            return None
        raise
    return [(str(row[0]), str(row[1]).upper()) for row in rows]


def count_rows(table_name: str) -> int | None:
    if table_schema(table_name) is None:
        return None
    return int(
        execute(f"select count() from {table_name}", timeout=30)["dataset"][0][0]
    )


def validate_full_table(table_name: str, wait_for_all_rows: bool = False) -> int:
    expected_schema = [(name, target_type.upper()) for name, target_type in SCHEMA]
    actual_schema = table_schema(table_name)
    if actual_schema != expected_schema:
        raise RuntimeError(
            f"{table_name} schema mismatch:\n"
            f"expected {expected_schema!r}\n"
            f"actual   {actual_schema!r}"
        )
    rows = count_rows(table_name)
    if wait_for_all_rows:
        deadline = time.monotonic() + 3600
        last_reported = None
        while rows != EXPECTED_ROWS and time.monotonic() < deadline:
            if rows is not None and rows > EXPECTED_ROWS:
                break
            if rows != last_reported:
                print(
                    f"Staging progress: {rows or 0:,} / {EXPECTED_ROWS:,} rows",
                    flush=True,
                )
                last_reported = rows
            time.sleep(2)
            rows = count_rows(table_name)
    if rows != EXPECTED_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_ROWS:,} rows in {table_name}, found {rows!r}"
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load the complete official 105-column ClickBench hits table."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="build and validate a new full table, then replace existing hits",
    )
    args = parser.parse_args()

    existing_schema = table_schema("hits")
    expected_schema = [(name, target_type.upper()) for name, target_type in SCHEMA]
    if existing_schema is not None:
        existing_rows = count_rows("hits")
        if existing_schema == expected_schema and existing_rows == EXPECTED_ROWS:
            if not args.force:
                print(
                    f"hits already has the complete {len(SCHEMA)}-column schema "
                    f"and {existing_rows:,} rows"
                )
                return
        elif not args.force:
            raise SystemExit(
                f"hits exists with {len(existing_schema)} columns and "
                f"{existing_rows:,} rows; use --force to replace it safely"
            )
        if not args.force:
            return

    staging_schema = table_schema(STAGING_TABLE)
    resume_staging = staging_schema == expected_schema
    if staging_schema is not None:
        if resume_staging:
            print(
                f"Resuming validation of existing {STAGING_TABLE} staging table...",
                flush=True,
            )
        elif not args.force:
            raise SystemExit(
                f"{STAGING_TABLE} exists from an earlier load; use --force to replace it"
            )
        else:
            execute(f"drop table {STAGING_TABLE}")
            resume_staging = False

    started = time.perf_counter()
    if resume_staging:
        result = {}
    else:
        if not DATASET.is_file() or DATASET.stat().st_size != EXPECTED_BYTES:
            raise SystemExit(
                f"Dataset is missing or incomplete: {DATASET}\n"
                f"Run {HERE / 'download.sh'} first."
            )
        print(
            f"Loading all {len(SCHEMA)} columns from the official ClickBench "
            "Parquet file into a staging table...",
            flush=True,
        )
        result = execute(FULL_TABLE_SQL)
    elapsed_ns = int(result.get("timings", {}).get("execute", 0))
    rows = validate_full_table(STAGING_TABLE, wait_for_all_rows=True)
    wall_seconds = time.perf_counter() - started

    if table_schema("hits") is not None:
        execute("drop table hits")
    execute(f"rename table {STAGING_TABLE} to hits")
    validate_full_table("hits")

    if elapsed_ns:
        print(
            f"Loaded {rows:,} rows and {len(SCHEMA)} columns in "
            f"{elapsed_ns / 1_000_000_000:.3f}s "
            f"server time ({wall_seconds:.3f}s wall)"
        )
    elif resume_staging:
        print(
            f"Validated and installed {rows:,} rows and {len(SCHEMA)} columns "
            f"in {wall_seconds:.3f}s wall time"
        )
    else:
        print(
            f"Loaded {rows:,} rows and {len(SCHEMA)} columns in "
            f"{wall_seconds:.3f}s wall time"
        )
    print(
        "The native hits table now matches the official QuestDB ClickBench "
        "column order, types, designated timestamp, and daily partitioning."
    )


if __name__ == "__main__":
    main()
