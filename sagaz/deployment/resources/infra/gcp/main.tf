# sagaz on GCP: outbox worker on a Cloud Run worker pool, Cloud SQL for
# PostgreSQL and Memorystore for Redis on private IPs. The resources are split
# by concern: network.tf, database.tf, redis.tf, secrets.tf, worker.tf.

locals {
  prefix = "${var.name}-${var.environment}"

  labels = merge(var.labels, {
    app         = "sagaz"
    environment = var.environment
    managed-by  = "terraform"
  })

  cdc_enabled = var.outbox_mode == "cdc"

  required_apis = toset([
    "compute.googleapis.com",
    "run.googleapis.com",
    "redis.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
  ])
}

resource "google_project_service" "apis" {
  for_each = var.enable_apis ? local.required_apis : toset([])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
