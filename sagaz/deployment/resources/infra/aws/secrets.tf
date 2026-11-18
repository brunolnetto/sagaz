# ---------------------------------------------------------------------------
# Generated credentials, stored in Secrets Manager and injected into the
# worker task as ECS secrets (never as plain environment variables).
#
# Passwords are alphanumeric so they can be embedded in URLs without escaping
# and satisfy the RDS / ElastiCache AUTH character rules.
# ---------------------------------------------------------------------------

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "redis" {
  length  = 48
  special = false
}

locals {
  database_url = format(
    "postgresql://%s:%s@%s:%d/%s?sslmode=require",
    var.db_username,
    random_password.db.result,
    aws_db_instance.this.address,
    aws_db_instance.this.port,
    var.db_name,
  )

  redis_url = format(
    "rediss://:%s@%s:%d/0",
    random_password.redis.result,
    aws_elasticache_replication_group.this.primary_endpoint_address,
    aws_elasticache_replication_group.this.port,
  )
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${local.prefix}/database-url"
  description             = "sagaz PostgreSQL connection URL (DATABASE_URL)"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.database_url
}

resource "aws_secretsmanager_secret" "redis_url" {
  name                    = "${local.prefix}/redis-url"
  description             = "sagaz Redis connection URL (REDIS_URL)"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = local.redis_url
}
