# VPC used for private connectivity. Cloud SQL and Memorystore get private IPs
# through Private Service Access (servicenetworking peering); the worker reaches
# them with Cloud Run Direct VPC egress from var.subnetwork (or the subnet below).

resource "google_compute_network" "this" {
  count = var.network == null ? 1 : 0

  project                 = var.project_id
  name                    = "${local.prefix}-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "this" {
  count = var.network == null ? 1 : 0

  project                  = var.project_id
  name                     = "${local.prefix}-subnet"
  region                   = var.region
  network                  = google_compute_network.this[0].id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

locals {
  network_id    = var.network == null ? google_compute_network.this[0].id : var.network
  subnetwork_id = var.network == null ? google_compute_subnetwork.this[0].id : var.subnetwork
}

resource "google_compute_global_address" "private_service_access" {
  count = var.create_private_service_access ? 1 : 0

  project       = var.project_id
  name          = "${local.prefix}-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_access_prefix_length
  network       = local.network_id

  depends_on = [google_project_service.apis]
}

resource "google_service_networking_connection" "private_service_access" {
  count = var.create_private_service_access ? 1 : 0

  network                 = local.network_id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_access[0].name]

  # Deleting the peering fails while Google still holds the released Cloud SQL
  # producer resources; abandon it so `terraform destroy` completes. The VPC
  # deletion then removes the peering with it.
  deletion_policy = "ABANDON"
}
