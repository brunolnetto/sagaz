# Connection URLs (with credentials) live in Secret Manager; the worker reads
# them as secret-backed environment variables.

locals {
  database_url = format(
    "postgresql://%s:%s@%s:5432/%s?sslmode=require",
    var.db_user,
    random_password.db.result,
    google_sql_database_instance.this.private_ip_address,
    var.db_name,
  )

  # Memorystore's server CA is not in the image trust store, so TLS is used for
  # encryption without certificate verification (ssl_cert_reqs=none).
  redis_url = var.redis_transit_encryption ? format(
    "rediss://:%s@%s:%d/0?ssl_cert_reqs=none",
    google_redis_instance.this.auth_string,
    google_redis_instance.this.host,
    google_redis_instance.this.port,
    ) : format(
    "redis://:%s@%s:%d/0",
    google_redis_instance.this.auth_string,
    google_redis_instance.this.host,
    google_redis_instance.this.port,
  )

  # Env var name => secret id. Values are looked up separately so for_each
  # never iterates over sensitive data.
  secret_ids = {
    DATABASE_URL = "${local.prefix}-database-url"
    REDIS_URL    = "${local.prefix}-redis-url"
  }
  secret_values = {
    DATABASE_URL = local.database_url
    REDIS_URL    = local.redis_url
  }
}

resource "google_secret_manager_secret" "this" {
  for_each = local.secret_ids

  project   = var.project_id
  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "this" {
  for_each = local.secret_ids

  secret      = google_secret_manager_secret.this[each.key].id
  secret_data = local.secret_values[each.key]
}

resource "google_secret_manager_secret_iam_member" "worker" {
  for_each = local.secret_ids

  project   = var.project_id
  secret_id = google_secret_manager_secret.this[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.worker.member
}
