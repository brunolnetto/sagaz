# sagaz on AWS (Terraform)

This module deploys a managed sagaz stack. `sagaz deploy --provider aws` uses it,
and you can also apply it with Terraform yourself.

| Component | AWS service | Notes |
|-----------|-------------|-------|
| Outbox worker (`python -m sagaz.core.outbox.worker`) | ECS Fargate service | `worker_count` tasks, logs to CloudWatch |
| Saga + outbox storage | RDS PostgreSQL 16 | gp3, encrypted, private, TLS enforced (`rds.force_ssl`) |
| Broker (Redis Streams) | ElastiCache Redis OSS 7 | single node, TLS in transit, at-rest encryption, AUTH token |
| Credentials | Secrets Manager | generated with `random_password` |

## Usage

```bash
cd sagaz/deployment/resources/infra/aws
terraform init
terraform apply -var image=ghcr.io/acme/sagaz:1.8.3
# or
terraform apply -var-file=examples/minimal.tfvars
```

Only `image` is required. It must be built from the repository `Dockerfile`.
The task definition sets the command to `python -m sagaz.core.outbox.worker`
(override it with `worker_command`).

### Main variables

| Variable | Default | Description |
|----------|---------|-------------|
| `name` / `environment` | `sagaz` / `prod` | Resource prefix is `<name>-<environment>` |
| `region` | `us-east-1` | AWS region |
| `tags` | `{}` | Extra tags on every resource |
| `image` | (required) | Worker container image |
| `worker_count` / `worker_cpu` / `worker_memory` | `1` / `256` / `512` | Fargate sizing (CPU units, MiB) |
| `worker_cpu_architecture` | `X86_64` | `ARM64` needs an arm64 image |
| `db_instance_class` / `db_storage_gb` / `db_multi_az` | `db.t4g.micro` / `20` / `false` | RDS sizing |
| `db_engine_version` | `16.10` | PostgreSQL version; the parameter group family follows the major version |
| `db_deletion_protection` | `false` | See [Teardown](#teardown) |
| `db_skip_final_snapshot` | `false` | A final snapshot is kept on destroy by default |
| `redis_node_type` | `cache.t4g.micro` | ElastiCache node type |
| `outbox_mode` | `polling` | `polling` or `cdc` (see [CDC](#cdc-mode)) |
| `vpc_id` / `subnet_ids` | `null` | Deploy into an existing VPC (see [Networking](#networking)) |
| `worker_assign_public_ip` | `true` | Public IP on worker tasks (needed without a NAT gateway) |
| `batch_size` / `poll_interval` / `max_retries` | `100` / `1` / `5` | Worker tuning (`BATCH_SIZE`, `POLL_INTERVAL`, `MAX_RETRIES`) |
| `worker_environment` | `{}` | Extra non-secret environment variables |
| `log_retention_days` | `30` | CloudWatch Logs retention |
| `secret_recovery_window_days` | `0` | `0` deletes secrets immediately on destroy so the same name can be redeployed |

The full list is in `variables.tf`.

### Outputs

`database_endpoint`, `redis_endpoint`, `worker_service_name`, `cluster_name`,
`log_group`, `region`, `vpc_id`, `database_url_secret_arn`, `redis_url_secret_arn`,
plus `database_url` and `redis_url`, which are sensitive. Read them with
`terraform output -raw database_url`.

## Networking

If `vpc_id` is `null` (the default), the module creates a small VPC across two AZs:

- **Public subnets** hold the worker tasks. Each task gets a public IP so it can pull
  the image and reach Secrets Manager and CloudWatch Logs. The worker security group
  allows **no inbound traffic**. Outbound traffic is limited to 443 and the database
  and Redis ports.
- **Private subnets** hold RDS and ElastiCache. They have no route to the internet,
  and neither service is publicly accessible. Only the worker security group can
  reach PostgreSQL (5432) and Redis (6379).

This avoids a NAT gateway, which costs about $33 per month plus data processing.

**NAT alternative:** to keep workers off public IPs, bring your own VPC with private
subnets behind a NAT gateway, or with VPC endpoints for ECR, Secrets Manager, Logs
and S3. Then pass `vpc_id`, `subnet_ids` (at least 2 subnets in different AZs) and
`worker_assign_public_ip = false`. With your own VPC, the workers, RDS and
ElastiCache all use `subnet_ids`.

The worker serves no HTTP endpoint (no metrics or health port). ECS restarts a task
whose process exits.

## Secrets

The database password and the Redis AUTH token come from `random_password`. They
are alphanumeric, so they are safe to embed in a URL. The full connection URLs are
stored in Secrets Manager under `<prefix>/database-url` and `<prefix>/redis-url`.
They are injected into the container as ECS `secrets` (`DATABASE_URL`, `REDIS_URL`),
never as plain environment variables. The task *execution* role can only call
`secretsmanager:GetSecretValue` on those two ARNs. The task role has no policies.

- `DATABASE_URL=postgresql://sagaz:…@<rds>:5432/sagaz?sslmode=require`
- `REDIS_URL=rediss://:…@<elasticache>:6379/0` with `BROKER_TYPE=redis`

The generated passwords are also kept in the Terraform state. Store state in an
encrypted backend with restricted access.

## CDC mode

With `outbox_mode = "cdc"`:

- The custom DB parameter group sets `rds.logical_replication = 1`. This also sets
  `wal_level = logical`.
- The worker gets `SAGAZ_OUTBOX_MODE=cdc` and `SAGAZ_CDC_SOURCE=pg_logical`.

`rds.logical_replication` is a static parameter, so the instance **must be rebooted**
before it takes effect. A fresh deploy with `cdc` creates the instance with the
parameter applied. Switching an existing stack from `polling` to `cdc` needs:

```bash
aws rds reboot-db-instance --db-instance-identifier <name>-<environment>-db
```

The worker connects as the master user, a member of `rds_superuser`, which can use
logical replication on RDS. For least privilege, create a dedicated role
(`CREATE ROLE sagaz_cdc LOGIN PASSWORD '…'; GRANT rds_replication TO sagaz_cdc;`)
and set `SAGAZ_CDC_DSN` through `worker_environment`, or better through a secret.
A replication slot retains WAL until the worker acknowledges it, so monitor
`pg_replication_slots` and the storage use (see `docs/integrations/cdc.md`).

## Teardown

`db_deletion_protection` defaults to **`false`** so that `sagaz deploy teardown` /
`terraform destroy` can remove the stack.

> **Warning:** for production data, set `db_deletion_protection = true`. Before
> tearing down, set it back to `false` and apply. Otherwise the destroy fails on
> the RDS instance.

By default (`db_skip_final_snapshot = false`), destroy keeps a final snapshot named
`<prefix>-db-final-<random>`. It is billed until you delete it. Set
`db_skip_final_snapshot = true` for throwaway stacks. Secrets are deleted
immediately (`secret_recovery_window_days = 0`).

## Cost

`cost.json` lists approximate us-east-1 on-demand prices. `sagaz deploy --cost-estimate`
reads it offline. The default stack (1 x 0.25 vCPU/0.5 GB worker, db.t4g.micro with
20 GB, cache.t4g.micro) costs roughly **$39/month** before data transfer and logs.
