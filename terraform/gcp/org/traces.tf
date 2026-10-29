# Org-wide traces: a trace scope lists every org project, so Trace Explorer in the
# scoping project can search them all. Traces stay in their own projects. Terraform
# cannot make it the default scope; see README.md for the one gcloud step.

resource "google_project_service" "observability" {
  project            = var.project_id
  service            = "observability.googleapis.com"
  disable_on_destroy = false
}

resource "google_observability_trace_scope" "org" {
  project        = var.project_id
  location       = "global"
  trace_scope_id = "org"
  description    = "Every active project in the org."
  resource_names = [for p in sort(tolist(local.org_projects)) : "projects/${p}"]

  lifecycle {
    precondition {
      condition     = length(local.org_projects) <= 20
      error_message = "A trace scope holds at most 20 projects; split it or use exclude_projects."
    }
  }

  depends_on = [google_project_service.observability]
}
