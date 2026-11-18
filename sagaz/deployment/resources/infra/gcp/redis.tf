# Memorystore for Redis (the outbox broker) on Private Service Access with AUTH.

resource "google_redis_instance" "this" {
  project            = var.project_id
  name               = "${local.prefix}-redis"
  region             = var.region
  tier               = var.redis_tier
  memory_size_gb     = var.redis_memory_size_gb
  redis_version      = var.redis_version
  authorized_network = local.network_id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  auth_enabled       = true
  labels             = local.labels

  transit_encryption_mode = var.redis_transit_encryption ? "SERVER_AUTHENTICATION" : "DISABLED"

  depends_on = [
    google_project_service.apis,
    google_service_networking_connection.private_service_access,
  ]
}
