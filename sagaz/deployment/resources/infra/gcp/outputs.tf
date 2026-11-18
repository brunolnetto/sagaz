output "database_endpoint" {
  description = "Private IP of the Cloud SQL instance (port 5432)."
  value       = google_sql_database_instance.this.private_ip_address
}

output "database_connection_name" {
  description = "Cloud SQL connection name (project:region:instance)."
  value       = google_sql_database_instance.this.connection_name
}

output "redis_endpoint" {
  description = "Memorystore host:port (private IP)."
  value       = "${google_redis_instance.this.host}:${google_redis_instance.this.port}"
}

output "worker_service_name" {
  description = "Name of the Cloud Run worker pool running the outbox worker."
  value       = google_cloud_run_v2_worker_pool.worker.name
}

output "worker_service_account" {
  description = "Service account the worker runs as."
  value       = google_service_account.worker.email
}

output "database_url" {
  description = "DATABASE_URL given to the worker (contains the password)."
  value       = local.database_url
  sensitive   = true
}

output "redis_url" {
  description = "REDIS_URL given to the worker (contains the AUTH string)."
  value       = local.redis_url
  sensitive   = true
}

output "secret_ids" {
  description = "Secret Manager secret ids holding DATABASE_URL and REDIS_URL."
  value       = { for k, s in google_secret_manager_secret.this : k => s.secret_id }
}

output "log_filter" {
  description = "Cloud Logging filter for the worker's logs."
  value       = local.log_filter
}

output "log_url" {
  description = "Logs Explorer URL for the worker's logs."
  value       = "https://console.cloud.google.com/logs/query;query=${urlencode(local.log_filter)}?project=${var.project_id}"
}

output "network" {
  description = "VPC network used for private connectivity."
  value       = local.network_id
}

output "cdc_setup_sql" {
  description = "SQL to run once (as a cloudsqlsuperuser, e.g. in Cloud SQL Studio) before the worker can create its replication slot in CDC mode; null in polling mode."
  value       = local.cdc_enabled ? "ALTER USER \"${var.db_user}\" WITH REPLICATION;" : null
}

locals {
  log_filter = "resource.type=\"cloud_run_worker_pool\" AND resource.labels.worker_pool_name=\"${local.prefix}-outbox-worker\""
}
