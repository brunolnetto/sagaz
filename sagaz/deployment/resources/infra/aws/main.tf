# sagaz managed stack on AWS: outbox worker on ECS Fargate, PostgreSQL on RDS,
# Redis (Streams broker) on ElastiCache. Resources are split by concern:
#   network.tf  - VPC/subnets (optional) and security groups
#   database.tf - RDS PostgreSQL
#   cache.tf    - ElastiCache Redis
#   secrets.tf  - generated credentials and Secrets Manager
#   worker.tf   - ECS cluster, task definition, service, IAM, logs

locals {
  prefix = "${var.name}-${var.environment}"

  tags = merge(
    {
      "app.kubernetes.io/part-of" = "sagaz"
      "sagaz:stack"               = local.prefix
      "sagaz:environment"         = var.environment
      "managed-by"                = "terraform"
    },
    var.tags,
  )

  cdc_enabled = var.outbox_mode == "cdc"
}
