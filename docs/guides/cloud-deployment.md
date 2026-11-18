# Cloud deployment

`sagaz deploy` runs the sagaz **outbox worker** in production on AWS, GCP or
Kubernetes, with a managed PostgreSQL for saga and outbox storage and Redis as the
message broker. `sagaz teardown` removes it. The Terraform modules and the Helm chart
ship with sagaz, under `sagaz/deployment/resources/infra/{aws,gcp}` and
`sagaz/deployment/resources/charts/sagaz`, so the commands work from a plain
`pip install sagaz`.

| Provider | Worker | Database | Broker |
|---|---|---|---|
| `aws` | ECS Fargate service | RDS PostgreSQL 16 | ElastiCache Redis 7 (TLS + AUTH) |
| `gcp` | Cloud Run worker pool | Cloud SQL PostgreSQL 16 (private IP) | Memorystore Redis (AUTH) |
| `k8s` | Deployment in your cluster (Helm) | Yours (any PostgreSQL URL) | Redis, Kafka or RabbitMQ |

## Before you start

1. **Build and push the worker image** from the repository's `Dockerfile` to a registry
   the target can pull from:

   ```bash
   docker build -t ghcr.io/acme/sagaz-worker:1.9.0 .
   docker push ghcr.io/acme/sagaz-worker:1.9.0
   ```

2. **Install the tool for your target**: [Terraform](https://developer.hashicorp.com/terraform/install)
   ≥ 1.6 for `aws` and `gcp`, [Helm](https://helm.sh/docs/intro/install/) 3 for `k8s`.
3. **Credentials**: the provider's usual mechanisms. That means AWS profiles or
   environment variables, `gcloud auth application-default login`, or the current
   kube context. sagaz never stores credentials.

## Deploy

```bash
# AWS: ECS + RDS + ElastiCache, region us-east-1 by default
sagaz deploy --provider aws --image ghcr.io/acme/sagaz-worker:1.9.0 --cost-estimate

# GCP: Cloud Run + Cloud SQL + Memorystore
sagaz deploy --provider gcp --project-id acme-prod \
    --image us-docker.pkg.dev/acme-prod/sagaz/worker:1.9.0 --region us-central1

# Kubernetes: the Helm chart in the current kube context
sagaz deploy --provider k8s --namespace sagaz --image ghcr.io/acme/sagaz-worker:1.9.0 \
    --values my-values.yaml
```

For `aws` and `gcp` the command:

1. copies the module into a local working directory, `.sagaz/deploy/<provider>`
   (`--state-dir` to change it). The Terraform state lives there: keep it, or
   configure a remote backend in that directory;
2. records the variables in `sagaz.auto.tfvars.json`;
3. runs `terraform init` and `terraform plan`;
4. asks for confirmation, then applies the plan and prints the non-sensitive outputs.

| Option | Effect |
|---|---|
| `--dry-run` | Stop after the Terraform plan (or render the Helm manifests with `helm template`, which needs no cluster). Nothing changes |
| `--cost-estimate` | Print an estimated monthly cost first ([below](#cost-estimate)) |
| `--var KEY=VALUE` | Set a Terraform variable or a Helm value. Values are parsed as JSON when possible (`--var worker_count=2`, `--var db_multi_az=true`) |
| `--values FILE` | Helm values file (`k8s`), repeatable |
| `--yes` | Do not ask for confirmation |
| `--name` | Resource prefix (cloud) or release name (`k8s`); default `sagaz` |

### Sizing and options

All variables have small defaults. The most useful overrides:

| Variable | `aws` default | `gcp` default |
|---|---|---|
| `worker_count` | `1` | `1` |
| `worker_cpu` / `worker_memory` | `256` / `512` (Fargate units) | `"1"` / `"512Mi"` |
| Database size | `db_instance_class = "db.t4g.micro"` | `db_tier = "db-f1-micro"` |
| Database HA | `db_multi_az = false` | `db_availability_type = "ZONAL"` |
| `db_storage_gb` | `20` | `10` |
| Redis | `redis_node_type = "cache.t4g.micro"` | `redis_tier = "BASIC"`, `redis_memory_size_gb = 1` |
| `outbox_mode` | `polling` | `polling` |

See each module's `README.md` for every variable: networking with your own VPC,
deletion protection, backups, log retention and TLS.

### Outputs

Both modules output `database_endpoint`, `redis_endpoint`, `worker_service_name`,
`database_url` and `redis_url`. The two URLs are sensitive: read them with
`terraform -chdir=.sagaz/deploy/aws output -raw database_url`. They are also stored in
the cloud secret manager, which is where the worker reads them from.

## Cost estimate

`--cost-estimate` prints a monthly estimate before anything runs. It is computed
offline from list prices shipped with each module (`cost.json`), the variables'
defaults and your `--var` overrides:

```text
Estimated monthly cost (aws, us-east-1, USD)
  RDS PostgreSQL instance (db.t4g.micro)          11.68
  ...
  Total                                           ~39
```

With the defaults, AWS comes to about **$39/month** and GCP to about **$95/month**.
Prices are approximate on-demand list prices (dated in the output), and exclude data
transfer, taxes and discounts. A size missing from the price list is shown as
"not priced" rather than guessed. Kubernetes has no estimate, since it depends on your
cluster.

## CDC mode

`--var outbox_mode=cdc` runs the worker with
[change data capture](../integrations/cdc.md) instead of polling.

- **AWS:** enables `rds.logical_replication`.
- **GCP:** enables `cloudsql.logical_decoding`. Afterwards, run the `ALTER USER … WITH
  REPLICATION` statement from the `cdc_setup_sql` output once, as an administrator.
- **Kubernetes:** `outbox.mode=cdc` with `outbox.cdc.source=pg_logical` forces a single
  replica with the `Recreate` strategy. A replication slot accepts one consumer at a
  time, and giving each pod its own slot would publish every event once per pod. The
  `debezium` source can run several replicas.

## Teardown

```bash
sagaz teardown --provider aws       # asks you to type the stack name
sagaz teardown --provider k8s --namespace sagaz
```

For `aws` and `gcp`, `teardown` runs `terraform destroy` in the same working directory,
with the recorded variables. **It deletes the database.** AWS keeps a final snapshot
unless `db_skip_final_snapshot = true`. Deletion protection is off by default so that
teardown works. For production, set `db_deletion_protection = true` (AWS) or
`deletion_protection = true` (GCP), and turn it off before tearing down.

## Kubernetes values

The chart takes the database and broker URLs as plain values (stored in a Secret it
creates) or from secrets you manage:

```yaml
image:
  repository: ghcr.io/acme/sagaz-worker
  tag: "1.9.0"
database:
  existingSecret: sagaz-db          # key: database-url
broker:
  type: redis                       # redis | kafka | rabbitmq
  existingSecret: sagaz-broker      # key: broker-url
outbox:
  mode: polling
replicaCount: 2
autoscaling:
  enabled: true                     # polling mode only
```

The chart runs the worker as a non-root user with a read-only root filesystem. The
worker serves no HTTP endpoint, so there are no probes or metrics port by default. See
the chart's `README.md` for every value. The chart bundles neither PostgreSQL nor Redis:
use managed services, existing charts, or the raw manifests in
`sagaz/deployment/resources/k8s` for local clusters.

## Notes

- The generated passwords are also stored in the Terraform state, so protect the state
  directory or use an encrypted remote backend.
- The worker connects with the database owner's credentials. For a least-privilege
  role, see the module READMEs.
- The modules are validated offline (`terraform validate` and, for GCP, `terraform test`
  with mocked providers), and the chart with `helm lint --strict` and `helm template`.
  They have not been applied by sagaz's test suite against real cloud accounts.
