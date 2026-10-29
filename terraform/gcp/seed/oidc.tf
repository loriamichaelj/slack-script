resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "Keyless access for ${var.github_owner}/${var.github_repo} workflows."

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  # checkov:skip=CKV_GCP_125: the check only accepts an exact assertion.sub match. This provider is shared by three environments, so it pins the immutable repository and owner IDs instead, and each environment is bound by its own subject below.
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  # Only tokens from this exact owner and repo, by immutable ID, are accepted.
  attribute_condition = "assertion.repository_owner_id == \"${var.github_owner_id}\" && assertion.repository_id == \"${var.github_repo_id}\""

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository_id"    = "assertion.repository_id"
    "attribute.environment"      = "assertion.environment"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

locals {
  pool_name = google_iam_workload_identity_pool.github.name

  # One subject per GitHub environment: the environment's own protection rules
  # (reviewers, branch policy) decide who can reach each service account.
  github_subjects = {
    seed = "${local.subject_prefix}:environment:SEED"
    dev  = "${local.subject_prefix}:environment:DEV"
    ci   = "${local.subject_prefix}:environment:CI"
  }
}

# SEED environment -> seed-admin
resource "google_service_account_iam_member" "seed_admin_wif" {
  service_account_id = google_service_account.seed_admin.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${local.pool_name}/subject/${local.github_subjects.seed}"
}

# CI environment (plan) -> tf-planner. CI needs a reviewer and allows any branch,
# so pull requests can plan.
resource "google_service_account_iam_member" "tf_planner_wif" {
  service_account_id = google_service_account.tf_planner.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${local.pool_name}/subject/${local.github_subjects.ci}"
}

# DEV environment (apply) and CI environment (destroy) -> dev-deployer
resource "google_service_account_iam_member" "dev_deployer_wif" {
  for_each = {
    dev = local.github_subjects.dev
    ci  = local.github_subjects.ci
  }

  service_account_id = google_service_account.dev_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${local.pool_name}/subject/${each.value}"
}
