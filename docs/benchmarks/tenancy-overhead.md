# Multi-tenancy overhead benchmark

How much slower are sagas when they run as many tenants instead of one? This page
answers the acceptance criterion of [#54](https://github.com/brunolnetto/sagaz/issues/54)
(ADR-020): *1000 tenants × 10 concurrent sagas with < 5% overhead versus single-tenant*,
with a scaled-down configuration measured on a laptop, and the command to run the full
size yourself.

**Result:** running sagas as many tenants adds no storage work on any backend (on
PostgreSQL: exactly the same 13 statements per saga) and 2.6–4.4 µs of client CPU per
saga, which is 0.02–0.41% of a saga's time on the measured backends. The end-to-end
medians are within the run-to-run noise of this shared machine (about ±15%), so they
neither show nor rule out a difference that small; the two load-independent measurements
are what establish the < 5% bound. The cost of tenancy *support* on PostgreSQL, paid by
single-tenant deployments too, is one `set_config` round trip per acquired connection
(2 of 13 statements per saga, about 16% of saga latency when the database round trip
dominates); row-level security itself costs nothing measurable. **Since #405, the
default tenant no longer pays it:** single-tenant sagas send 11 statements, the same
as with no tenant SQL at all (see [After #405](#after-405-the-default-tenant-skips-set_config)).

## What is measured

The harness lives in [`benchmarks/tenancy/`](https://github.com/brunolnetto/sagaz/tree/develop/benchmarks/tenancy)
(outside the `sagaz` package: it needs real databases, and it is not shipped).

- **Workload**: a declarative saga with four steps (`reserve` → `charge` → `ship` →
  `notify`; the first two with compensations), its state persisted at start and end
  through `SagaConfig(storage=...)`, with metrics and logging listeners off. Steps do no
  simulated work by default (`--step-sleep-ms 0`): sleeping would add the same fixed
  wait to both modes and hide the overhead, so this is the worst case for the ratio.
- **Modes**, on the same storage, with the same number of sagas:
  - `baseline`: every saga in the default tenant (`Saga.run(ctx)`, no `tenant_context`);
  - `multi`: T tenants × S concurrent sagas, each run with
    `tenant_context=TenantContext(...)` and quotas set to exactly the load
    (`max_concurrent_sagas=S`, plus step-duration and retry caps), so quota checks run
    on every saga but never reject;
  - `multi-registry`: the same, with tenant ids resolved through a `TenantRegistry`.
- **Concurrency**: T × S workers start together, each running `--sagas-per-worker` sagas
  one after another. In `baseline` the same number of workers runs without tenants.
- **Interleaving**: each round runs every mode once, back to back, the order rotated
  each round (AB, BA, AB, … for two modes; rotated for more). Each run is checked: no
  saga may fail, no state may fail to persist (sagaz only logs such failures), and
  sampled sagas must be stored as completed in their own tenant and invisible to the
  default tenant. Before each run all live objects are frozen out of the garbage
  collector (the in-memory store keeps every saga, and collecting that growing heap
  made each run slower than the last).
- **Reported**: throughput (sagas per second of wall time), p50/p95/p99 saga latency,
  each as the median over rounds, and the overhead of a mode over a reference, computed
  per round as `wall(mode) / wall(reference) − 1` and reported as median [min, max].
- **Load-independent measurements**:
  - *Tenancy machinery*: the work `Saga.run(..., tenant_context=...)` adds (resolve the
    tenant, check the context, take a quota slot, enter the scope, copy the context),
    timed alone in a loop, and its share of each backend's time per saga.
  - *Statements per saga* (PostgreSQL): every statement sent through asyncpg is counted
    while 20 sagas run in each mode.
- **PostgreSQL**: the harness creates a scratch database and a `NOSUPERUSER NOBYPASSRLS`
  role that owns the tables, so the `FORCE` row-level security policy applies, and runs
  *both* modes as that role. The ablation modes (`--postgres-ablations`) turn row-level
  security off on the saga tables (`*-rls-off`), and additionally skip the `set_config`
  sagaz runs on every acquired connection (`baseline-no-tenant-sql`, which is close to
  pre-tenancy sagaz: tenant column and filters remain).

## Machine

| | |
|---|---|
| CPU | 11th Gen Intel Core i7-11390H, 8 logical CPUs (4 cores × 2 threads) |
| RAM | 12 GB (11,963 MB), shared with other workloads |
| OS | `Linux 6.18.58.1-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC Tue Oct 27 00:24:11 UTC 2026 x86_64 GNU/Linux` (WSL2) |
| Python | 3.13.5 |
| PostgreSQL | 16.15 (`postgres:16-alpine`, Docker 29.9.3 via testcontainers) |
| Redis | 7.4.6 (`redis:7-alpine`) |
| SQLite | 3.49.1, file in a temporary directory |
| sagaz | commit `498c8d6` (develop + this change) |

The machine was **not idle**: other development sessions, test suites and containers
ran throughout (load average 4–7 during the documented runs, up to 18 during earlier
runs). Throughput varied by up to 3× between consecutive runs of the same mode, and runs
occasionally stalled for 20–25 s (seen on PostgreSQL with synchronous commit and on
SQLite, in every mode alike, consistent with disk flush stalls). Hence the
interleaving, the medians, and the load-independent measurements below.

## Results: 100 tenants × 10 concurrent sagas

```bash
python -m benchmarks.tenancy --backends memory,sqlite,postgres,redis \
    --postgres-admin-url postgresql://postgres:***@localhost:PORT/test \
    --redis-url redis://localhost:PORT \
    --json docs/benchmarks/tenancy-overhead.json
```

Defaults: 100 tenants × 10 concurrent sagas = 1,000 sagas per run, 1 warm-up run per
mode, 10 measured rounds; PostgreSQL pool of 20 connections, synchronous commit on.
Raw data: [`tenancy-overhead.json`](tenancy-overhead.json).

| Backend | Mode | Sagas/s (median) | Sagas/s range | p50 ms | p95 ms | p99 ms | Overhead vs baseline (median [min, max]) |
|---|---|---:|---:|---:|---:|---:|---|
| memory | baseline | 936 | 538-1,447 | 719.4 | 959.0 | 983.7 | - |
| memory | multi | 873 | 483-1,097 | 762.9 | 1033.3 | 1054.9 | +15.6% [-15.5%, +73.7%] |
| memory | multi-registry | 907 | 704-1,346 | 773.1 | 1007.6 | 1026.0 | -5.7% [-23.6%, +49.2%] |
| sqlite | baseline | 452 | 205-706 | 1929.2 | 2073.3 | 2086.1 | - |
| sqlite | multi | 396 | 264-669 | 2172.3 | 2366.9 | 2374.6 | +9.4% [-30.8%, +52.1%] |
| sqlite | multi-registry | 383 | 171-659 | 2190.9 | 2460.4 | 2483.2 | +14.5% [-19.4%, +42.5%] |
| postgres | baseline | 191 | 44-243 | 3867.5 | 4949.1 | 5045.5 | - |
| postgres | multi | 211 | 166-245 | 3128.9 | 4397.0 | 4425.8 | -8.6% [-73.3%, +10.1%] |
| postgres | multi-registry | 180 | 37-223 | 3695.9 | 5245.9 | 5273.6 | +2.8% [-69.4%, +119.5%] |
| redis | baseline | 650 | 473-766 | 1149.8 | 1388.9 | 1412.0 | - |
| redis | multi | 643 | 603-848 | 1184.9 | 1403.3 | 1421.8 | +0.7% [-24.6%, +20.8%] |
| redis | multi-registry | 690 | 516-800 | 1109.2 | 1305.5 | 1322.5 | -2.6% [-26.1%, +21.2%] |

Latencies are high because all 1,000 sagas start at once: p50 is mostly time spent
queued behind the other sagas (for the event loop, the SQLite connection or the
PostgreSQL pool), equally in every mode.

Load-independent measurements from the same run:

| | |
|---|---|
| Tenancy machinery per saga | 4.4 µs with a `TenantContext`, 4.3 µs with a registry id |
| Share of a saga's time (baseline `1 / throughput`) | memory 0.41%, SQLite 0.20%, PostgreSQL 0.08%, Redis 0.28% |
| PostgreSQL statements per saga | baseline 13, multi 13, multi-registry 13 |

## PostgreSQL: where tenancy support costs time

Sequential sagas (one worker, so latency is not queueing), commits not waiting for the
WAL flush so that per-statement costs are not hidden behind it, with the ablation
modes; 200 sagas per run, 15 rounds:

```bash
python -m benchmarks.tenancy --backends postgres --postgres-admin-url ... \
    --postgres-async-commit --postgres-ablations \
    --tenants 1 --sagas-per-tenant 1 --sagas-per-worker 200 --rounds 15 \
    --json docs/benchmarks/tenancy-overhead-postgres-ablations.json
```

Raw data: [`tenancy-overhead-postgres-ablations.json`](tenancy-overhead-postgres-ablations.json).

| Mode | RLS | `set_config` per connection | Statements per saga | p50 ms per saga (median of rounds) |
|---|---|---|---:|---:|
| baseline | on | yes | 13 | 12.1 |
| multi | on | yes | 13 | 12.3 |
| multi-registry | on | yes | 13 | 12.3 |
| baseline-rls-off | off | yes | 13 | 12.3 |
| multi-rls-off | off | yes | 13 | 12.4 |
| baseline-no-tenant-sql | off | no | 11 | 10.3 |

The paired wall-time overheads of this run are in the JSON and the harness output; they
are dominated by stalls (ranges of ±50% and more), so the per-saga p50 is the better
measure here.

- **Multi-tenant versus single-tenant**: the same statements, and p50 within 0.2 ms
  (12.3 versus 12.1 ms, inside the noise).
- **Row-level security**: no measurable cost (12.1 ms with, 12.3 ms without). The policy
  predicate is evaluated on rows already found through the `(tenant_id, saga_id)` key.
- **`set_config` per acquired connection**: 2 of the 13 statements of a saga (one per
  `save_saga_state`, i.e. per connection acquisition), and 2.0 ms of 12.3 ms (about 16%,
  `baseline-rls-off` versus `baseline-no-tenant-sql`) in this round-trip-bound setup,
  in line with its 2/13 share of the round trips. It is paid in every mode, including single-tenant
  deployments, because asyncpg's pool runs `RESET ALL` when a connection is released,
  so the tenant setting must be set again on every acquisition. With synchronous commit
  (the default, and the main table) the commit flush dominates and the share is smaller.

## Does it meet < 5%?

| Backend | Extra storage work per saga in `multi` | Client CPU added per saga | Share of saga time | End-to-end median (noise ±15%) |
|---|---|---:|---:|---:|
| in-memory | none (partition lookup by tenant) | 4.4 µs | 0.41% | +15.6% / −5.7% |
| SQLite | none (same statements, other tenant value) | 4.4 µs | 0.20% | +9.4% / +14.5% |
| PostgreSQL | none (13 = 13 statements; RLS not measurable) | 4.4 µs | 0.08% | −8.6% / +2.8% |
| Redis | none (same commands, tenant key prefix) | 4.4 µs | 0.28% | +0.7% / −2.6% |

Yes, on every backend, by the measurements that can resolve it: multi-tenant sagas do
no extra storage work, and the extra client work is well under 1% of a saga. The
end-to-end medians cannot resolve 5% on this machine. Note that `multi` and
`multi-registry` do the same work (the registry adds a dictionary lookup), yet their
medians differ by 21 points on the in-memory backend: that difference is the noise
floor, and every end-to-end median above is inside it.

Before this change the machinery measured 27–36 µs per saga during the loaded runs
(2% of an in-memory saga in the run that measured both). Most of it was generator-based
context managers: an `@asynccontextmanager` for the quota slot nested with a
`@contextmanager` for the scope, plus asyncio's bookkeeping of every async generator.
`tenant_execution` is now a small class: 9.7 → 3.0 µs for the wrapper alone, old and
new interleaved in one process. Inside whole in-memory sagas the difference is below
what this machine can resolve.

## After #405: the default tenant skips `set_config`

The improvement suggested by this benchmark was made in #405. Pools sagaz creates now
reset each released connection to the default tenant within asyncpg's own reset round
trip, and sagaz remembers which connections are known to be at the default. An
acquisition for the default tenant on such a connection skips the `set_config`. Any
other tenant, and any connection sagaz does not know, is still set every time, so
isolation is unchanged; tests cover a connection released by one tenant being reused by
the default tenant, as a `NOSUPERUSER NOBYPASSRLS` role.

Statements per saga, measured after the change (local PostgreSQL 16.15, 20 tenants × 5
sagas, 3 rounds, with ablations):

| Mode | Before #405 | After #405 |
|---|---:|---:|
| baseline (default tenant) | 13 | **11** |
| baseline, RLS off | 13 | **11** |
| baseline, no tenant SQL | 11 | 11 |
| multi / multi-registry (other tenants) | 13 | 13 |

Single-tenant deployments now send exactly the statements they would without tenancy
support. Multi-tenant sagas still set their tenant once per acquisition.

## Run the full size

The criterion's configuration, 1000 tenants × 10 concurrent sagas (10,000 sagas per
run):

```bash
python -m benchmarks.tenancy --tenants 1000 --sagas-per-tenant 10 \
    --backends memory,sqlite,postgres,redis \
    --postgres-admin-url postgresql://postgres:PASSWORD@HOST:5432/postgres \
    --redis-url redis://HOST:6379 \
    --json tenancy-overhead-full.json
```

- `--postgres-admin-url` needs a role that may create databases and roles; the
  benchmark creates `sagaz_bench_*` (database and `NOSUPERUSER NOBYPASSRLS` role) and
  drops both at the end. With `--postgres-url` it uses an existing database and role as
  they are (use a scratch database: its rows are left behind; the ablations need the
  role to own the tables).
- Redis keys use a unique `sagaz-bench-*` prefix (with a one-hour TTL) and are deleted
  at the end.
- Expect about 10× the time of the scaled-down run (which took 7 minutes for all four
  backends here, so over an hour). The in-memory backend keeps every saga of its session,
  about 8 KB each: 33 runs × 10,000 sagas is roughly 2.6 GB, so check free memory first
  or run it separately with fewer rounds. The other backends hold only the sagas in
  flight.
- On a quiet machine, add rounds (`--rounds 20`) for tighter medians; `--help` lists
  every option, including `--step-sleep-ms` for simulated step work.

The scaled-down default (100 × 10) keeps one run around a second in-memory and a few
seconds on the I/O backends, so 10 interleaved rounds of three modes on four backends
fit in about 10 minutes on a shared laptop; the per-saga work and every per-tenant
structure (partitions, key prefixes, quota counters) are exercised the same way.

## Automated check

`tests/integration/test_tenancy_overhead.py` (markers `integration`, `performance`,
`slow`; not part of the unit suite) runs 20 tenants × 5 sagas for 7 rounds on every
backend (PostgreSQL as an ordinary role, via the test containers) and asserts:

- PostgreSQL row-level security is enforced, and a multi-tenant saga sends exactly as
  many statements as a single-tenant one;
- the median paired overhead stays below **50%**. The bound is deliberately loose: on a
  shared laptop a single pair of runs can differ by ±40% without any code change, so it
  only catches gross regressions (an extra query per step, a pool per tenant), not the
  < 5% target, which the statement count and the machinery timing cover.

```bash
pytest tests/integration/test_tenancy_overhead.py -m performance -v -s
```
