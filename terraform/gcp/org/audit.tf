# Audit events that matter every time, counted per minute as log-based metrics on the org log
# bucket, so they cover every org project, including ones created later. The alert job reads
# them as logging.googleapis.com/user/<name> in the scoping project, split by `source` (the
# project, folder or org the entry came from), and alerts on any count above zero.
#
# Admin Activity audit logs are always on and free. The metrics are billed as custom metrics,
# which at a handful of events a day stays inside the free allotment.
locals {
  activity = "logName:\"cloudaudit.googleapis.com%2Factivity\""

  audit_metrics = {
    # IAM policy of the org, a folder or a project changed, or an org policy changed.
    "audit-iam-changes" = {
      description = "IAM or org policy changes on the org, folders or projects."
      filter      = "${local.activity} AND ((protoPayload.serviceName=\"cloudresourcemanager.googleapis.com\" AND protoPayload.methodName=\"SetIamPolicy\") OR protoPayload.serviceName=\"orgpolicy.googleapis.com\")"
    }
    # A long-lived service account key: the credential most often leaked.
    "audit-sa-key-created" = {
      description = "Service account keys created."
      filter      = "${local.activity} AND protoPayload.methodName=\"google.iam.admin.v1.CreateServiceAccountKey\""
    }
    # Someone changed where logs go, or what is dropped: the first step in covering tracks.
    "audit-logging-changed" = {
      description = "Log sinks, buckets or exclusions changed or deleted."
      filter      = "${local.activity} AND protoPayload.serviceName=\"logging.googleapis.com\" AND (protoPayload.methodName:\"DeleteSink\" OR protoPayload.methodName:\"UpdateSink\" OR protoPayload.methodName:\"DeleteBucket\" OR protoPayload.methodName:\"UpdateBucket\" OR protoPayload.methodName:\"Exclusion\")"
    }
    # A bucket opened to everyone, or a firewall rule opened to the whole internet.
    "audit-made-public" = {
      description = "Buckets granted to allUsers or allAuthenticatedUsers, and firewall rules opened to 0.0.0.0/0."
      filter      = "${local.activity} AND ((protoPayload.methodName=\"storage.setIamPermissions\" AND (protoPayload.serviceData.policyDelta.bindingDeltas.member=\"allUsers\" OR protoPayload.serviceData.policyDelta.bindingDeltas.member=\"allAuthenticatedUsers\")) OR (resource.type=\"gce_firewall_rule\" AND protoPayload.request.sourceRanges=\"0.0.0.0/0\"))"
    }
    # The footprint grew or moved: a project created, moved or deleted, or an API turned on.
    "audit-new-footprint" = {
      description = "Projects created, moved or deleted, and APIs enabled."
      filter      = "${local.activity} AND ((protoPayload.serviceName=\"cloudresourcemanager.googleapis.com\" AND (protoPayload.methodName:\"CreateProject\" OR protoPayload.methodName:\"MoveProject\" OR protoPayload.methodName:\"DeleteProject\")) OR protoPayload.methodName=\"google.api.serviceusage.v1.ServiceUsage.EnableService\" OR protoPayload.methodName=\"google.api.serviceusage.v1.ServiceUsage.BatchEnableServices\")"
    }
    # Destroying a key version makes everything encrypted with it unreadable for good.
    "audit-kms-key-destroyed" = {
      description = "KMS key versions scheduled for destruction."
      filter      = "${local.activity} AND protoPayload.methodName:\"DestroyCryptoKeyVersion\""
    }
  }
}

resource "google_logging_metric" "audit" {
  for_each    = local.audit_metrics
  project     = var.project_id
  name        = each.key
  description = each.value.description
  bucket_name = google_logging_project_bucket_config.org.id
  filter      = each.value.filter

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "source"
      value_type  = "STRING"
      description = "Project, folder or org the entry came from."
    }
  }
  label_extractors = {
    source = "REGEXP_EXTRACT(logName, \"^(?:projects|folders|organizations)/([^/]+)/\")"
  }
}
