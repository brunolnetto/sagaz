# ---------------------------------------------------------------------------
# ElastiCache Redis (Redis Streams broker)
#
# Single node replication group: encryption in transit (TLS, so the URL is
# rediss://) and at rest, AUTH token required.
# ---------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.prefix}-redis"
  subnet_ids = local.data_subnet_ids
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.prefix}-redis"
  description          = "sagaz Redis broker (${local.prefix})"

  engine               = "redis"
  engine_version       = var.redis_engine_version
  node_type            = var.redis_node_type
  num_cache_clusters   = 1
  port                 = 6379
  parameter_group_name = "default.redis${split(".", var.redis_engine_version)[0]}"

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.redis.id]

  automatic_failover_enabled = false
  multi_az_enabled           = false

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis.result

  apply_immediately = true

  tags = { Name = "${local.prefix}-redis" }
}
