output "database_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)."
  value       = aws_db_instance.this.endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint (host:port)."
  value       = "${aws_elasticache_replication_group.this.primary_endpoint_address}:${aws_elasticache_replication_group.this.port}"
}

output "worker_service_name" {
  description = "ECS service running the outbox worker."
  value       = aws_ecs_service.worker.name
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "database_url" {
  description = "PostgreSQL connection URL (DATABASE_URL) including credentials."
  value       = local.database_url
  sensitive   = true
}

output "redis_url" {
  description = "Redis connection URL (REDIS_URL, rediss:// with AUTH token)."
  value       = local.redis_url
  sensitive   = true
}

output "log_group" {
  description = "CloudWatch log group of the outbox worker."
  value       = aws_cloudwatch_log_group.worker.name
}

output "region" {
  description = "AWS region of the stack."
  value       = var.region
}

output "vpc_id" {
  description = "VPC the stack runs in."
  value       = local.vpc_id
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN holding DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "redis_url_secret_arn" {
  description = "Secrets Manager ARN holding REDIS_URL."
  value       = aws_secretsmanager_secret.redis_url.arn
}
