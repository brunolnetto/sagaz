# The outbox worker is a long-running consumer with no HTTP server, so it runs
# on a Cloud Run *worker pool* (GA): always-on instances, no port, no request
# endpoint and no startup probe on $PORT. A Cloud Run service would fail its
# default TCP startup probe because the worker never listens on $PORT.

resource "google_service_account" "worker" {
  project = var.project_id
  # account_id is limited to 30 characters.
  account_id   = "${substr(local.prefix, 0, 23)}-worker"
  display_name = "sagaz outbox worker (${var.environment})"
}

resource "google_project_iam_member" "worker_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.worker.member
}

locals {
  worker_env = merge(
    {
      BROKER_TYPE       = "redis"
      REDIS_SSL         = var.redis_transit_encryption ? "true" : "false"
      SAGAZ_OUTBOX_MODE = var.outbox_mode
    },
    local.cdc_enabled ? { SAGAZ_CDC_SOURCE = "pg_logical" } : {},
    { for k, v in var.worker_env : k => v if !contains(keys(local.secret_ids), k) },
  )
}

resource "google_cloud_run_v2_worker_pool" "worker" {
  project             = var.project_id
  name                = "${local.prefix}-outbox-worker"
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.labels

  scaling {
    scaling_mode          = "MANUAL"
    manual_instance_count = var.worker_count
  }

  template {
    service_account = google_service_account.worker.email
    labels          = local.labels

    vpc_access {
      # Direct VPC egress: private ranges (Cloud SQL / Memorystore PSA IPs) go
      # through the VPC, everything else (Google APIs, registries) directly.
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = local.network_id
        subnetwork = local.subnetwork_id
      }
    }

    containers {
      name    = "outbox-worker"
      image   = var.image
      command = slice(var.worker_command, 0, 1)
      args    = slice(var.worker_command, 1, length(var.worker_command))

      resources {
        limits = {
          cpu    = var.worker_cpu
          memory = var.worker_memory
        }
      }

      dynamic "env" {
        for_each = local.worker_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_ids
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret = google_secret_manager_secret.this[env.key].secret_id
              # Pinned so a rotated URL rolls out a new revision.
              version = google_secret_manager_secret_version.this[env.key].version
            }
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.network == null || var.subnetwork != null
      error_message = "subnetwork is required when network is set (Direct VPC egress takes IPs from it)."
    }
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.worker,
    google_project_iam_member.worker_cloudsql_client,
  ]
}
