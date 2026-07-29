# Clickbench Q10 Experiments
Conducted on Macbook M1 Max with 64GiB RAM, 8 performance + 2 efficiency cores.

Profile only Q10:
```
./artifacts/clickbench/run.sh profile -t clickbench -- start -e cpu -i 5ms

./artifacts/clickbench/bench.py q10 \
--warmups 3 --runs 10 --no-result

./artifacts/clickbench/run.sh profile -t clickbench -- \
stop -f /tmp/clickbench-q10.html
```

## Hits table and query details
Hits table has 22 daily partitions, containing ~99m rows total.
```
 SELECT name, numRows, diskSizeHuman
  FROM table_partitions('hits');
```


Timestamp range: 2013-07-01 20:00:00Z through 2013-07-31 19:59:59Z.

Full table is ~67GiB, but only a few GiB in the 3 columns that we need.

### Query pipeline
Query plan is:
```
"QUERY PLAN"
"Long Top K lo: 10"
"  keys: [u desc]"
"    Async JIT Group By workers: 8"
"      keys: [MobilePhoneModel]"
"      values: [count_distinct(UserID)]"
"      filter: MobilePhoneModel is not null"
"        PageFrame"
"            Row forward scan"
"            Frame forward scan on: hits"
```

All partitions are scanned and frames are produced. From frames, which contain
only projected columns, records are produced, which are immediately filtered, grouped into a hashh table keyed by `MobilePhoneModel`, whose values are hash sets of `UserId`s. This is all parallelized/async, unit of parallelism being a frame, accumulated into per-worker fragments, sharded by hash into 256 shards. Merge is done on top of this, also in parallel. And then top-K is computed, where we look up for top 10 counts in descending order, with a single worker.

## Baseline with 10 query workers
scattered across both efficiency and performance cores most likely
- median: 117.7ms
- minimum: 109ms

## Baseline with only 8 query workers
cold query: 1169ms

5 warmups then 30 measured warm runs:
- median: 104ms
- minimum: 97.1ms
- mean: 107ms
- p95: 116ms

### Analysis
CPU profiling shows that the most expensive part is `CountDistinctLongGroupByFunction.computeNext`, and then within it `GroupByLongHashSet.keyIndex`. CPU is important here, since all data fits memory, and there's no contention.

Q10 has:
- 5,563,212 qualifying rows.
- 165 phone model groups.
- 1,188,468 final group-distinct entries.
- One highly dominant model with 1,090,347 distinct users.

Nearly every qualifying row performs:

`setA.of(ptr).keyIndex(value)`

Thus millions of keyIndex() calls per execution are expected. It is doing the core work

**Potential bottlenecks**:
1. Skew in phone models - during merge of shards, each model will belong only to a single shard. Most popular models will have largest hash sets of distinct users to merge, and this will create worker imbalance.
2. Merge causes expensive rehashing. 42% of CPU samples of `merge` function are under `rehash`.

## Experiment 1: 2nd shard level with UserID
Baseline plan has issue that it's prone to skewed shards, where even the highest cardinality phone models are still going to be processed only by a single worker.

These figures use CPU samples from only the eight shared-query workers; owner/network-thread work
stealing is excluded.
```

Phase                           Canonical Q10    16-bucket Q10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━
Scan/aggregation worker CV               4.5%             7.9%
──────────────────────────────  ───────────────  ───────────────
Scan max/min                            1.17×            1.21×
──────────────────────────────  ───────────────  ───────────────
Merge worker CV                         92.1%            19.2%
──────────────────────────────  ───────────────  ───────────────
Merge max/min                            117×            1.75×
──────────────────────────────  ───────────────  ───────────────
Hottest worker’s merge share            36.0%            17.9%
──────────────────────────────  ───────────────  ───────────────
Top two workers’ merge share            63.4%            31.7%
```
(CV = stdev / mean * 100%)

So we can see that the worker imbalance is real during merge.

Simply doing:
```
SELECT MobilePhoneModel, COUNT(*) AS u
FROM (
    SELECT DISTINCT MobilePhoneModel, UserID
    FROM hits
    WHERE MobilePhoneModel IS NOT NULL
      AND UserID IS NOT NULL
) distinct_pairs
GROUP BY MobilePhoneModel
ORDER BY u DESC
LIMIT 10;
```
mimics what we want to do. Even better, we could do:
```
SELECT MobilePhoneModel, sum(bucket_u) AS u
  FROM (
      SELECT
          MobilePhoneModel,
          cast(UserID & 15 AS int) AS uid_bucket,
          count_distinct(UserID) AS bucket_u
      FROM hits
      WHERE MobilePhoneModel IS NOT NULL
      GROUP BY MobilePhoneModel, uid_bucket
  )
  GROUP BY MobilePhoneModel
  ORDER BY u DESC
  LIMIT 10;
```
which makes hash table keys smaller and is enough for our data.

It produces this query plan:
```
"QUERY PLAN"
"Long Top K lo: 10"
"  keys: [u desc]"
"    GroupBy vectorized: false"
"      keys: [MobilePhoneModel]"
"      values: [sum(bucket_u)]"
"        VirtualRecord"
"          functions: [MobilePhoneModel,bucket_u]"
"            Async JIT Group By workers: 8"
"              keys: [MobilePhoneModel,uid_bucket]"
"              keyFunctions: [UserID&15::int]"
"              values: [count_distinct(UserID)]"
"              filter: MobilePhoneModel is not null"
"                PageFrame"
"                    Row forward scan"
"                    Frame forward scan on: hits"

```
The final GroupBy is serial, but it's fine, as it's only 165 distinct non-null phone models, split into 16 user ID buckets.

Here are the results:
```
Query          Minimum          Mean        Median
━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━━━━  ━━━━━━━━━━━━
Canonical    95.446 ms    113.421 ms    104.859 ms
───────────  ───────────  ────────────  ────────────
Bucketed     85.241 ms    103.139 ms     95.119 ms
```

So this is a query rewrite, but it's just a PoC that if engine changes were made to use second level of bucketing, performance gains could be made.

## Experiment 2 (incremental): presize hash tables to avoid rehashing during merge.

```
Query                  Min       Median         Mean           p95
━━━━━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━━━━
Canonical Q10    91.876 ms    97.549 ms    98.098 ms    105.217 ms
───────────────  ───────────  ───────────  ───────────  ────────────
16-bucket Q10    84.307 ms    89.419 ms    91.842 ms    107.194 ms
```
Canonical Q10 improved more, but for bucketed one mean and median also improved a couple of percents.


## Experiment 3 (incremental): unordered map for composite keys
When we switched to using composite key of model + user, the engine
fell back to using ordered map, instead of an unordered map.

# Sorted partitions
Didn't explore this, but if partitions were finer-grained, and also sorted by model+user, we could explore streaming top-K execution. This might not be according to benchmark spec though.

The streaming execution would:
```
Scan sorted runs
    ->
K-way merge by (model, user)
    ->
Remove adjacent duplicate pairs
    ->
Streaming count by model
    ->
Top-10 heap
```
