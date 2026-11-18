# Offline plan tests: `terraform test` with mocked providers (no credentials,
# no API calls). Run from the module directory after `terraform init -backend=false`.

mock_provider "google" {
  mock_resource "google_sql_database_instance" {
    defaults = {
      private_ip_address = "10.20.0.3"
      connection_name    = "demo:us-central1:sagaz-prod-pg-abcd"
    }
  }
  mock_resource "google_redis_instance" {
    defaults = {
      host        = "10.20.0.4"
      port        = 6379
      auth_string = "redis-auth"
    }
  }
  mock_resource "google_service_account" {
    defaults = {
      email  = "sagaz-prod-worker@demo.iam.gserviceaccount.com"
      member = "serviceAccount:sagaz-prod-worker@demo.iam.gserviceaccount.com"
    }
  }
  mock_resource "google_compute_network" {
    defaults = {
      id = "projects/demo/global/networks/sagaz-prod-vpc"
    }
  }
  mock_resource "google_compute_subnetwork" {
    defaults = {
      id = "projects/demo/regions/us-central1/subnetworks/sagaz-prod-subnet"
    }
  }
}

mock_provider "random" {}

variables {
  project_id = "demo"
  image      = "us-docker.pkg.dev/demo/sagaz/worker:latest"
}

run "defaults_polling" {
  command = apply

  assert {
    condition     = google_cloud_run_v2_worker_pool.worker.scaling[0].manual_instance_count == 1
    error_message = "one always-on worker by default"
  }

  assert {
    condition     = google_sql_database_instance.this.settings[0].ip_configuration[0].ipv4_enabled == false
    error_message = "Cloud SQL must not have a public IP"
  }

  assert {
    condition     = length(google_sql_database_instance.this.settings[0].database_flags) == 0
    error_message = "no logical decoding flag in polling mode"
  }

  assert {
    condition     = google_redis_instance.this.auth_enabled
    error_message = "Memorystore AUTH must be enabled"
  }

  assert {
    condition     = output.redis_url == "redis://:redis-auth@10.20.0.4:6379/0"
    error_message = "unexpected REDIS_URL"
  }

  assert {
    condition     = startswith(output.database_url, "postgresql://sagaz:") && endswith(output.database_url, "@10.20.0.3:5432/sagaz?sslmode=require")
    error_message = "unexpected DATABASE_URL"
  }

  assert {
    condition     = output.cdc_setup_sql == null
    error_message = "no CDC setup in polling mode"
  }

  assert {
    condition     = google_sql_database_instance.this.deletion_protection == false
    error_message = "deletion protection is off by default so teardown works"
  }
}

run "cdc_tls" {
  command = apply

  variables {
    outbox_mode              = "cdc"
    redis_transit_encryption = true
    worker_count             = 2
  }

  assert {
    condition     = one(google_sql_database_instance.this.settings[0].database_flags).name == "cloudsql.logical_decoding"
    error_message = "CDC needs cloudsql.logical_decoding"
  }

  assert {
    condition     = google_redis_instance.this.transit_encryption_mode == "SERVER_AUTHENTICATION"
    error_message = "transit encryption expected"
  }

  assert {
    condition     = startswith(output.redis_url, "rediss://")
    error_message = "TLS URL expected"
  }

  assert {
    condition     = output.cdc_setup_sql == "ALTER USER \"sagaz\" WITH REPLICATION;"
    error_message = "CDC setup SQL expected"
  }
}

run "rejects_bad_outbox_mode" {
  command = plan

  variables {
    outbox_mode = "push"
  }

  expect_failures = [var.outbox_mode]
}

run "existing_network_requires_subnetwork" {
  command = plan

  variables {
    network = "projects/demo/global/networks/shared"
  }

  expect_failures = [google_cloud_run_v2_worker_pool.worker]
}
