# QuestDB ClickBench development loop

`ClickBenchTest` is an optimizer-plan regression test. It creates an empty
`hits` table and asserts `EXPLAIN` plans; it does not load data or measure
performance.

This directory adds a server-level performance loop around the canonical
queries in that test, with Q10 as the default:

```sql
SELECT MobilePhoneModel, count_distinct(UserID) AS u
FROM hits
WHERE MobilePhoneModel IS NOT NULL
GROUP BY MobilePhoneModel
ORDER BY u DESC
LIMIT 10;
```

The setup downloads the official 14.8 GB, 99,997,497-row ClickBench Parquet
file, builds this checkout, runs the resulting server, and creates the complete
native 105-column `hits` table using the upstream QuestDB schema. It preserves
the official column order and types, designated `EventTime`, and
`PARTITION BY DAY` layout. The loader converts the Parquet physical
representations for timestamps, IPv4 values, symbols, narrow integers, and
empty strings into the types the official QuestDB CSV workflow creates.

## One-time setup

From the repository root:

```bash
git submodule update --init java-questdb-client
./artifacts/clickbench/setup-jdk.sh
./artifacts/clickbench/download.sh
./artifacts/clickbench/build.sh
./artifacts/clickbench/start.sh
./artifacts/clickbench/load.py
```

The workspace-local JDK is used only by these scripts. QuestDB data lives in
`artifacts/clickbench/root`, so Maven builds do not delete it.

After a successful load, the Parquet download may be deleted to reclaim 14 GB;
the native table is self-contained. `load.py` recognizes an already-valid
table without the source file. Run `download.sh` again only when recreating it.

## Benchmark Q10

The default is 3 warmups followed by 10 measured runs:

```bash
./artifacts/clickbench/bench.py q10
```

Use fewer iterations while developing:

```bash
./artifacts/clickbench/bench.py q10 --warmups 1 --runs 3
```

This workspace also preserves the earlier three-column Q10 projection as
`hits_q10_projection`. It is not representative of the full ClickBench table,
but it can be measured explicitly to quantify that physical-layout difference:

```bash
./artifacts/clickbench/bench.py q10 --table hits_q10_projection
./artifacts/clickbench/bench.py q10 --table hits
```

The primary metric is QuestDB's `timings.execute` server time. Wall time is
shown separately to make HTTP/client overhead visible. Compare distributions,
not a single lucky minimum; median is a good default for the tight loop.

## Edit, rebuild, restart, benchmark

After changing QuestDB source:

```bash
./artifacts/clickbench/cycle.sh --warmups 3 --runs 10
```

`build.sh` is incremental, and the server restart reuses the loaded table.
`cycle.sh` stops the old process before staging the newly built JAR. This is
required because overwriting the module-path JAR of a live JVM can break lazy
class loading. For before/after comparisons, use the same build flags, JVM,
data root, warmup count, run count, and machine load.

The first build also downloads and embeds the QuestDB web console. Later
incremental builds reuse that bundle and stage the current JAR plus the
repository's official launch scripts under `artifacts/clickbench/runtime`.

## Plan regression test

Run the existing empty-table plan assertions separately:

```bash
./artifacts/clickbench/test-plans.sh
```

That catches plan-shape regressions but provides no latency measurement.

## All queries

`bench.py` parses all 43 query strings directly from
`core/src/test/java/io/questdb/test/griffin/ClickBenchTest.java`, so it cannot
silently drift from the test:

```bash
./artifacts/clickbench/bench.py q28 --warmups 1 --runs 3
./artifacts/clickbench/bench.py all --warmups 1 --runs 3
```

`all` runs the 43 query strings sequentially. For a quick compatibility pass
without warmups or result printing:

```bash
./artifacts/clickbench/bench.py all --warmups 0 --runs 1 --no-result
```

The upstream reference workflow downloads `hits.csv.gz`, decompresses it,
creates `hits` from the same DDL, and imports the 76 GB CSV through `/imp`.
This setup uses the official compatible Parquet dataset to avoid retaining that
additional 76 GB source file, while producing the same native QuestDB schema.

The upstream `questdb/` scripts are the canonical submission workflow, but they
target Linux and install a released QuestDB binary. This local layer instead
builds and restarts the current source checkout, which is required for a tight
engine-development loop.

## Server controls

```bash
./artifacts/clickbench/start.sh
./artifacts/clickbench/stop.sh
./artifacts/clickbench/run.sh status -t clickbench
./artifacts/clickbench/run.sh start -n -d artifacts/clickbench/root -t clickbench
tail -f artifacts/clickbench/root/log/stdout-*.txt
```

`run.sh` is an exact pass-through to the staged
`core/src/main/bin/questdb.sh`. This exposes every launcher command and option
without duplicating them in the ClickBench wrapper. `start.sh` and `stop.sh`
only add the default data root and process tag; any extra arguments are
forwarded:

```bash
# Background start with continuous async-profiler.
./artifacts/clickbench/start.sh -p -- \
  start,event=cpu,file=/tmp/clickbench-%n.jfr,interval=10ms

# Attach async-profiler to an already-running tagged server.
./artifacts/clickbench/run.sh profile -t clickbench -- \
  -e cpu -d 30 -f /tmp/clickbench.html
```

For a profile containing only the benchmark loop, start and stop attachment
around Q10:

```bash
./artifacts/clickbench/run.sh profile -t clickbench -- start -e cpu -i 5ms
./artifacts/clickbench/bench.py q10 --warmups 3 --runs 10 --no-result
./artifacts/clickbench/run.sh profile -t clickbench -- \
  stop -f /tmp/clickbench-q10.html
```

Measure the baseline again without an active profiler before comparing query
performance; sampling has overhead.

The repository's bundled async-profiler binaries are staged on Linux. On
macOS, `build.sh` downloads the pinned async-profiler 4.5 release, verifies its
published SHA-256 checksum, and adapts its `.dylib` name to the filename
currently expected by `questdb.sh`.

The web console is available at <http://127.0.0.1:9000/>.

By default these scripts set `shared.worker.count=8`, which gives the network,
query, and write shared pools eight workers each. This matches the eight
performance cores on the benchmark Mac; macOS still controls placement because
its Mach affinity tags are scheduling hints rather than hard CPU pinning. To
compare another parallel width:

```bash
CLICKBENCH_WORKER_COUNT=10 ./artifacts/clickbench/start.sh
```

On this benchmark host, macOS 26.5 rejects `THREAD_AFFINITY_POLICY` with
`KERN_NOT_SUPPORTED`, so do not set QuestDB's shared-worker affinity variables.
For a supported best-effort performance policy, launch the normal server with
macOS application mode and tier-0 throughput/latency policies:

```bash
taskpolicy -a -t 0 -l 0 ./artifacts/clickbench/start.sh
```

This is not P-core pinning, and the measured Q10 result was slightly slower
than the default scheduler, so it is intentionally not enabled by default.
