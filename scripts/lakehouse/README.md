# Local lakehouse: Fluss, Flink and Iceberg without Docker

`lakehouse.sh` runs the streaming analytics stack of ADR-013 on one machine
from pinned binary distributions:

- **Apache Fluss** 1.0.0, a local cluster;
- **Apache Flink** 1.20.5, a standalone cluster that runs the tiering job;
- **Apache Iceberg** 1.10.1, with its catalog in PostgreSQL (JDBC catalog) and
  its warehouse on local disk.

## Requirements

- **JDK 11 or later.** 17 is recommended; set `JAVA_HOME` if `java` is not on
  the `PATH`.
- **PostgreSQL** reachable for the Iceberg catalog. `start` creates the
  `iceberg` database if `psql` is available.
- About 1.5 GB of disk and 4 GB of free memory.
- **No `ulimit -v`** in the shell that starts the clusters: JVMs reserve large
  virtual address ranges.

## Use

```bash
scripts/lakehouse/lakehouse.sh fetch     # once: downloads and verifies checksums
scripts/lakehouse/lakehouse.sh start     # Fluss on localhost:9123, Flink UI on :8083
scripts/lakehouse/lakehouse.sh tiering   # the Fluss -> Iceberg tiering job

sagaz analytics export --saga-log postgresql://... --to fluss://localhost:9123

scripts/lakehouse/lakehouse.sh sql       # Flink SQL, catalogs `fluss` and `iceberg`
scripts/lakehouse/lakehouse.sh stop      # or reset: stop and delete everything
```

The exporter creates `sagaz.saga_log_event` in Fluss with
`table.datalake.enabled`. The tiering job writes it to the Iceberg table
`sagaz.saga_log_event`, in the JDBC catalog named `iceberg`, once per freshness
interval (`--freshness` on `sagaz analytics export`; Fluss's default is 3min).

```sql
-- History: the Iceberg table (batch).
SET 'execution.runtime-mode' = 'batch';
SELECT tenant_id, COUNT(*) FROM iceberg.sagaz.saga_log_event GROUP BY tenant_id;

-- Real time: the Fluss table (streaming).
SET 'execution.runtime-mode' = 'streaming';
SELECT event_type, COUNT(*) FROM fluss.sagaz.saga_log_event GROUP BY event_type;
```

Fluss 1.0 cannot read a primary-key table in batch as a union of Fluss and
Iceberg: `lake records must instance of sorted view`. Query history from the
`iceberg` catalog and fresh data from the Fluss stream.

`reset` stops both clusters and deletes the Fluss and ZooKeeper data, the
warehouse and the catalog database, so the next `start` begins empty.

## Settings

| Variable | Default |
|----------|---------|
| `LAKEHOUSE_HOME` | `~/.cache/sagaz/lakehouse` |
| `ICEBERG_JDBC_URL` | `jdbc:postgresql://localhost:5432/iceberg` |
| `ICEBERG_JDBC_USER` / `ICEBERG_JDBC_PASSWORD` | `postgres` / empty |
| `ICEBERG_WAREHOUSE` | `file://$LAKEHOUSE_HOME/warehouse` |
| `FLUSS_BOOTSTRAP` | `localhost:9123` |
| `FLINK_REST_PORT` | `8083` |

For S3 or MinIO, set `ICEBERG_WAREHOUSE=s3://bucket/path` and add
`iceberg-aws` and `iceberg-aws-bundle` (the Iceberg version above) to Flink's
`lib/` and Fluss's `plugins/iceberg/`, with the S3 `io-impl` and credentials
(see the Fluss "Deploying Streaming Lakehouse" guide).
