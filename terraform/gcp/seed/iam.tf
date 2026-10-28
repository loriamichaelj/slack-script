# Identities created by SEED. Service accounts do not support labels.

# Used by the SEED environment to manage this directory.
resource "google_service_account" "seed_admin" {
  account_id   = "seed-admin"
  display_name = "SEED Terraform"
  description  = "Applies terraform/gcp/seed from GitHub Actions."

  depends_on = [google_project_service.apis]
}

# Used by the DEV environment (apply) and the CI environment (destroy).
resource "google_service_account" "dev_deployer" {
  account_id   = "dev-deployer"
  display_name = "DEV Terraform"
  description  = "Applies and destroys terraform/gcp/dev from GitHub Actions."

  depends_on = [google_project_service.apis]
}

# Identity the Cloud Run job runs as. Created here so DEV only has to use it.
resource "google_service_account" "runtime" {
  account_id   = "anomaly-runtime"
  display_name = "Anomaly alerts runtime"
  description  = "Runs the anomaly-alerts job. Read-only on metrics."

  depends_on = [google_project_service.apis]
}

locals {
  seed_admin_roles = [
    "roles/iam.serviceAccountAdmin",
    "roles/iam.workloadIdentityPoolAdmin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
  ]

  dev_deployer_roles = [
    "roles/artifactregistry.admin",
    "roles/cloudscheduler.admin",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/storage.admin",
  ]
}

resource "google_project_iam_member" "seed_admin" {
  # checkov:skip=CKV_GCP_49: seed-admin creates and manages the service accounts by design. It is reachable only from the SEED environment, which needs a reviewer and is limited to the dev branch.
  for_each = toset(local.seed_admin_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.seed_admin.email}"
}

resource "google_project_iam_member" "dev_deployer" {
  for_each = toset(local.dev_deployer_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.dev_deployer.email}"
}

# The deployer may attach the runtime account to the Cloud Run job, and nothing else.
resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.dev_deployer.email}"
}

# The job reads Cloud Monitoring metrics. Secret and app-state access are granted
# per resource by DEV.
resource "google_project_iam_member" "runtime_monitoring" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
