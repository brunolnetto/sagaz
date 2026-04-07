# Sagaz GCP Terraform Module
# Provisions: Cloud Run, Cloud SQL (PostgreSQL), Memorystore (Redis)

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "project" {}
variable "region" { default = "us-central1" }
variable "name_prefix" { default = "sagaz" }

provider "google" {
  project = var.project
  region  = var.region
}

# Cloud Run service, Cloud SQL instance, Memorystore instance would be here.
# See docs/guides/cloud-deployment.md for full configuration.

output "cloud_run_url" {
  value = "https://${var.name_prefix}-<hash>-uc.a.run.app"
}
