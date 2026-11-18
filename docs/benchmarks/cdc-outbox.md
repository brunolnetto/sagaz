# CDC outbox: throughput and lag

How quickly outbox events reach the broker with the worker in CDC mode
(`PgLogicalSource`, PostgreSQL logical replication) compared with polling, for issue #50
([ADR-011](../architecture/adr/adr-011-cdc-support.md), guide:
[Change Data Capture](../integrations/cdc.md)).

The issue targets 50,000 events/s sustained with a p99 lag under 10 ms. As agreed for
#50, this is a scaled-down run on a laptop, with the numbers measured here and the
harness to repeat it anywhere.

## What is measured

`python -m benchmarks.cdc` inserts outbox rows straight into `saga_outbox` at a target
rate, from one or more producer connections, in transactions of 50 rows. A worker,
either in CDC mode or polling, publishes them to an in-process broker that records when
each event arrived.

- **Lag:** from the moment the producer's `COMMIT` returns to the broker's publish
  call. This is slightly *less* than the true commit-to-publish time.
- **Throughput:** events published per second, from the first commit to the last
  publication.

The worker does everything it does in production: tenant scope, publish, `SENT` status.
Only the broker is in-process. A real broker adds its own publish latency to both modes
alike.

## Machine

| | |
|---|---|
| CPU | 11th Gen Intel Core i7-11390H, 8 logical CPUs |
| Memory | 12 GB, shared with other workloads |
| OS | Linux 6.18 (WSL2), x86_64 |
| PostgreSQL | 16.15, local, `wal_level=logical`, `synchronous_commit=on`, `shared_buffers=128MB` |
| Python | 3.13.5 |

## Results

20,000 events per run, 4 producer connections, polling interval 1 s (the worker
default), and `PgLogicalSource` defaults (5 ms batching wait). The raw data is in
[`cdc-outbox.json`](cdc-outbox.json).

| Target rate | Mode | Produced/s | Published/s | Lag p50 | p95 | p99 | max |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1,000/s | **CDC** | 1,009 | 1,009 | **8.3 ms** | 33 ms | 110 ms | 194 ms |
| 1,000/s | polling | 1,004 | 952 | 484 ms | 1.16 s | 1.50 s | 1.59 s |
| 5,000/s | **CDC** | 5,006 | **4,990** | **13 ms** | 57 ms | 142 ms | 223 ms |
| 5,000/s | polling | 5,029 | 1,351 | 6.4 s | 10.3 s | 10.8 s | 10.9 s |
| unthrottled | **CDC** | 7,536 | **7,444** | 34 ms | 63 ms | 74 ms | 79 ms |
| unthrottled | polling | 20,810 | 1,476 | 6.9 s | 12.1 s | 12.6 s | 12.6 s |

- **CDC keeps up with the producers** in every run (published ≈ produced), up to the
  ~7,400 events/s this machine reached. The lag stays in milliseconds.
- **Polling saturates at ~1,000–1,500 events/s.** Above that it falls behind and the lag
  grows into seconds. Even at 1,000/s its median lag is half the poll interval, as
  expected.

### What shaped these numbers

- **Marking events `SENT` in one statement per batch.** Before this, every event cost
  its own `UPDATE` round trip, and CDC saturated at ~1,000–1,200 events/s, with lag
  growing into seconds above that. With one `UPDATE … WHERE event_id = ANY(…)` per
  batch (`mark_sent_batch`), it keeps up with the producers.
- **The batching wait is the floor of the lag.** At 1,000 events/s from a single
  producer, the p50/p99 lag was:

  | `max_batch_delay` | p50 | p95 | p99 |
  |---|---:|---:|---:|
  | 50 ms | 54 ms | 63 ms | 75 ms |
  | 5 ms (default) | 8 ms | 12 ms | 28 ms |
  | 1 ms | 3.8 ms | 8.7 ms | 14 ms |

  Lowering it did not reduce throughput measurably, so the default is now 5 ms.
- **Noise:** other workloads shared the machine, and unthrottled runs varied by
  ±40–50% between repetitions (from 2,700 to 6,800 events/s in one series). The
  pattern above, CDC keeping up and polling saturating, held in every repetition.

## Against the issue's target

| Target | Here | Status |
|---|---|---|
| 50,000 events/s sustained | ~7,400 events/s published, limited by the producers and a single worker on a laptop | not demonstrated at this scale |
| p99 lag < 10 ms | 1,000/s: p99 28 ms with the default wait, 14 ms with a 1 ms wait; p95 under 10 ms with a 1 ms wait | close, not met |

What would close the gap:

- **Throughput scales with workers.** Each worker needs its own slot (one consumer per
  slot) or a Debezium topic with several partitions consumed by a group.
- **The CDC worker handles batches one at a time:** publish, then mark `SENT`, then
  acknowledge. Pipelining the `SENT` marking (it is off the delivery path: a failure
  only means a later republish) would raise one worker's ceiling.
- **The local PostgreSQL commits synchronously on a laptop disk.** A server-class
  database and asynchronous commit move the producer limit well above this.

## Running it

```bash
# A scratch PostgreSQL with wal_level=logical. The harness truncates saga_outbox there.
python -m benchmarks.cdc --dsn postgresql://postgres@localhost:5432/scratch \
    --events 20000 --rates 1000 5000 0 --producers 4 --json results.json

# Lag floor vs batching wait:
python -m benchmarks.cdc --dsn ... --rates 1000 --modes cdc --max-batch-delay 0.001
```

Each CDC run creates its own replication slot and publication and drops them afterwards.
