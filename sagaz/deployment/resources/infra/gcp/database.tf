# Cloud SQL for PostgreSQL on a private IP only (no public IPv4).

resource "random_id" "db_suffix" {
  # Cloud SQL instance names cannot be reused for about a week after deletion.
  byte_length = 2
}

resource "random_password" "db" {
  length = 32
  # Alphanumeric only: the password is embedded in DATABASE_URL unescaped.
  special = false
}

resource "google_sql_database_instance" "this" {
  project             = var.project_id
  name                = "${local.prefix}-pg-${random_id.db_suffix.hex}"
  region              = var.region
  database_version    = var.db_version
  deletion_protection = var.deletion_protection

  settings {
    edition                     = var.db_edition
    tier                        = var.db_tier
    availability_type           = var.db_availability_type
    disk_type                   = "PD_SSD"
    disk_size                   = var.db_storage_gb
    disk_autoresize             = true
    deletion_protection_enabled = var.deletion_protection
    user_labels                 = local.labels

    ip_configuration {
      ipv4_enabled    = false
      private_network = local.network_id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = var.db_backups_enabled
      point_in_time_recovery_enabled = var.db_backups_enabled
    }

    # CDC (SAGAZ_OUTBOX_MODE=cdc, pg_logical) needs logical decoding. Changing
    # this flag restarts the instance.
    dynamic "database_flags" {
      for_each = local.cdc_enabled ? [1] : []
      content {
        name  = "cloudsql.logical_decoding"
        value = "on"
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_service_networking_connection.private_service_access,
  ]
}

resource "google_sql_database" "this" {
  project  = var.project_id
  name     = var.db_name
  instance = google_sql_database_instance.this.name
}

resource "google_sql_user" "this" {
  project  = var.project_id
  name     = var.db_user
  instance = google_sql_database_instance.this.name
  password = random_password.db.result

  # The user owns objects the worker creates; dropping it before the instance
  # is deleted would fail, and the instance deletion removes it anyway.
  deletion_policy = "ABANDON"
}
