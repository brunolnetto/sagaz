# sagaz Helm chart

Deploys the sagaz **transactional outbox worker** (`python -m sagaz.core.outbox.worker`)
to Kubernetes. The worker reads pending events from the PostgreSQL outbox (by polling,
or by change data capture) and publishes them to Redis, Kafka or RabbitMQ.

`sagaz deploy --provider k8s --namespace <ns>` installs this chart into the current kube
context; the equivalent Helm command is:

```bash
helm upgrade --install sagaz ./charts/sagaz \
  --namespace sagaz --create-namespace \
  --set image.repository=registry.example.com/sagaz-outbox-worker \
  --set image.tag=1.8.3 \
  -f my-values.yaml
```

## Dependencies are not bundled

The chart installs only the worker. PostgreSQL and the broker are expected to exist:
use managed services (RDS/Cloud SQL, MSK/Confluent, ElastiCache, Amazon MQ...) or
releases of their own charts (e.g. Bitnami `postgresql`, `redis`, `kafka`, `rabbitmq`).
For a local cluster, the raw manifests under `sagaz/deployment/resources/k8s/`
(`database/simple`, `database/ha`, `monitoring`) bring up PostgreSQL and observability.

The worker creates its tables on start (`CREATE TABLE IF NOT EXISTS`), so there is no
migration Job.

## Required values

Rendering fails unless both are set:

| Value | Purpose |
|---|---|
| `database.url` or `database.existingSecret` (+ `database.existingSecretKey`, default `database-url`) | PostgreSQL connection string (`DATABASE_URL`) |
| `broker.url` or `broker.existingSecret` (+ `broker.existingSecretKey`, default `broker-url`) | Broker URL, exposed as `REDIS_URL` / `KAFKA_BOOTSTRAP_SERVERS` / `RABBITMQ_URL` (per `broker.type`) and `BROKER_URL` |

Plain `url` values are stored in a Secret created by the chart. With `existingSecret`
for both (and for the CDC DSN, if used), the chart creates no Secret.

## Values

| Key | Default | Description |
|---|---|---|
| `image.repository` | `sagaz-outbox-worker` | Worker image (built from the repository `Dockerfile`) |
| `image.tag` | chart `appVersion` | Image tag |
| `image.pullPolicy` | `IfNotPresent` | |
| `imagePullSecrets` | `[]` | |
| `command` / `args` | worker entry point / `[]` | Container command |
| `replicaCount` | `1` | Workers (ignored with `autoscaling.enabled`) |
| `logLevel` | `INFO` | `LOG_LEVEL` |
| `broker.type` | `kafka` | `redis`, `kafka` or `rabbitmq` (`BROKER_TYPE`) |
| `broker.rabbitmq.exchange` | `saga-events` | `RABBITMQ_EXCHANGE` |
| `outbox.mode` | `polling` | `polling` or `cdc` (`SAGAZ_OUTBOX_MODE`) |
| `outbox.batchSize` | `100` | `BATCH_SIZE` |
| `outbox.pollInterval` | `1.0` | `POLL_INTERVAL` (seconds) |
| `outbox.maxRetries` | `5` | `MAX_RETRIES` |
| `outbox.cdc.source` | `pg_logical` | `pg_logical` or `debezium` (`SAGAZ_CDC_SOURCE`) |
| `outbox.cdc.sweepInterval` / `sweepMinAge` | `30` / `30` | `SAGAZ_CDC_SWEEP_INTERVAL` / `SAGAZ_CDC_SWEEP_MIN_AGE` |
| `outbox.cdc.pgLogical.slot` / `publication` | `sagaz_outbox` / `sagaz_outbox_pub` | `SAGAZ_CDC_SLOT` / `SAGAZ_CDC_PUBLICATION` |
| `outbox.cdc.pgLogical.dsn` or `existingSecret` (+ `existingSecretKey`, default `cdc-dsn`) | empty | Replication DSN (`SAGAZ_CDC_DSN`); defaults to the database URL |
| `outbox.cdc.debezium.bootstrapServers` | empty | Kafka Debezium writes to; required unless `broker.type=kafka` |
| `outbox.cdc.debezium.topicPrefix` / `groupId` | `sagaz` / `sagaz-cdc` | `SAGAZ_CDC_TOPIC_PREFIX` / `SAGAZ_CDC_GROUP_ID` |
| `extraEnv` / `extraEnvFrom` | `[]` | Extra environment |
| `extraVolumes` / `extraVolumeMounts` | `[]` | e.g. broker TLS material |
| `serviceAccount.create` / `name` / `annotations` / `automountServiceAccountToken` | `true` / `""` / `{}` / `false` | |
| `podAnnotations` / `podLabels` | `{}` | |
| `podSecurityContext` | non-root uid/gid 1000, `seccompProfile: RuntimeDefault` | |
| `securityContext` | no privilege escalation, read-only root fs, drop `ALL` capabilities | `/tmp` is an `emptyDir` |
| `resources` | 100m / 128Mi requests, 512Mi memory limit | |
| `livenessProbe` / `readinessProbe` | `{}` | The worker serves no HTTP; add exec probes if wanted |
| `terminationGracePeriodSeconds` | `30` | Time to finish the in-flight batch after SIGTERM |
| `nodeSelector` / `tolerations` / `affinity` / `topologySpreadConstraints` / `priorityClassName` | empty | Scheduling |
| `autoscaling.enabled` / `minReplicas` / `maxReplicas` / `targetCPUUtilizationPercentage` / `targetMemoryUtilizationPercentage` / `behavior` | `false` / `2` / `10` / `70` / `null` / `{}` | HPA, polling mode only |
| `podDisruptionBudget.enabled` / `minAvailable` / `maxUnavailable` | `true` / `null` / `1` | Set one of the two |
| `metrics.enabled` / `port` / `path` | `false` / `8000` / `/metrics` | Port, scrape annotations and a metrics Service |
| `metrics.serviceMonitor.enabled` / `interval` / `scrapeTimeout` / `labels` | `false` / `30s` / `10s` / `{}` | Prometheus Operator ServiceMonitor |

`values.schema.json` validates types and enums; cross-field rules are enforced at render
time (see below).

## Scaling and CDC

- **Polling** (`outbox.mode=polling`) scales horizontally: workers claim batches with
  `FOR UPDATE SKIP LOCKED`, so any number of replicas, or the HPA, is safe.
- **CDC with `pg_logical`** reads one PostgreSQL replication slot. A slot accepts a
  single consumer at a time, so a second replica would fail to attach; giving each pod
  its own slot would not help either, because every slot receives every outbox insert
  and each pod would publish each event again. The chart therefore **fails rendering
  unless `replicaCount=1`**, rejects `autoscaling.enabled`, and uses the `Recreate`
  rollout strategy so the old pod releases the slot before the new one starts. High
  availability comes from Kubernetes restarting the pod; events committed meanwhile wait
  in the slot (and the sweep picks up stragglers). Watch the slot's retained WAL
  (`pg_replication_slots`) and set `max_slot_wal_keep_size`.
- **CDC with `debezium`** consumes a Kafka consumer group, so `replicaCount` can be raised
  up to the topic's partition count; the HPA is still polling-only.

The default image installs the `postgres`, `kafka`, `rabbitmq`, `tracing` and
`prometheus` extras. CDC needs the `cdc` extra (`pip install 'sagaz[cdc]'`) in the image.
See `docs/integrations/cdc.md` for PostgreSQL prerequisites.

## Metrics

The stock worker entry point does **not** start an HTTP metrics server. `metrics.enabled`
only adds the container port, `prometheus.io/*` annotations, a Service and (optionally)
a ServiceMonitor; enable it with an image or command that serves metrics, e.g. one that
calls `sagaz.observability.monitoring.prometheus.start_metrics_server(port)` before
starting the worker.

## Linting

`ci/*.yaml` are the variants used for linting and the unit tests
(`tests/unit/deployment/test_helm_chart.py`):

```bash
for f in ci/*.yaml; do helm lint --strict . -f "$f"; helm template sagaz . -f "$f" >/dev/null; done
```
