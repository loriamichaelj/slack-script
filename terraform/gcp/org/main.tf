# Makes the scoping project's metrics scope cover every active project in the org,
# so one Cloud Monitoring query sees them all. Covers projects directly under the
# org and under its top-level folders. Re-apply when projects are added.

data "google_folders" "top" {
  parent_id = "organizations/${var.org_id}"
}

data "google_projects" "under_org" {
  filter = "parent.type:organization parent.id:${var.org_id} lifecycleState:ACTIVE"
}

data "google_projects" "under_folder" {
  for_each = toset([for f in data.google_folders.top.folders : trimprefix(f.name, "folders/")])

  filter = "parent.type:folder parent.id:${each.value} lifecycleState:ACTIVE"
}

locals {
  org_projects = toset(concat(
    [for p in data.google_projects.under_org.projects : p.project_id],
    flatten([for d in data.google_projects.under_folder : [for p in d.projects : p.project_id]]),
  ))

  # The scoping project is always in its own scope.
  monitored = setsubtract(local.org_projects, concat([var.project_id], var.exclude_projects))
}

resource "google_monitoring_monitored_project" "org" {
  for_each = local.monitored

  metrics_scope = "locations/global/metricsScopes/${var.project_id}"
  name          = each.value
}
