# One Cloud Run job per command, each started by its own Cloud Scheduler job.
locals {
  config_path = "${local.mount_path}/config.yaml"

  jobs = {
    "anomaly-run" = {
      args     = ["--config", local.config_path]
      schedule = "*/5 * * * *" # matches the 5 minute metric period
      secrets  = { SLACK_WEBHOOK_URL = "slack-webhook" }
    }
    "routine-heartbeat" = {
      args     = ["routine", "--kind", "heartbeat", "--config", local.config_path]
      schedule = "0 */6 * * *"
      secrets  = { SLACK_WEBHOOK_URL = "slack-webhook", SLACK_ROUTINE_WEBHOOK_URL = "slack-routine-webhook" }
    }
    "routine-digest" = {
      args     = ["routine", "--kind", "digest", "--config", local.config_path]
      schedule = "0 9 * * *"
      secrets  = { SLACK_WEBHOOK_URL = "slack-webhook", SLACK_ROUTINE_WEBHOOK_URL = "slack-routine-webhook" }
    }
    "routine-cost" = {
      args     = ["routine", "--kind", "cost", "--config", local.config_path]
      schedule = "30 9 * * *"
      secrets  = { SLACK_WEBHOOK_URL = "slack-webhook", SLACK_ROUTINE_WEBHOOK_URL = "slack-routine-webhook" }
    }
  }
}

resource "google_cloud_run_v2_job" "job" {
  for_each = local.jobs

  name                = each.key
  location            = var.region
  deletion_protection = false # DEV is meant to be torn down

  template {
    task_count = 1

    template {
      service_account       = local.runtime_sa
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # needed for the bucket mount
      timeout               = "300s"
      max_retries           = 0 # a retry could post the same alert twice; the next run picks it up

      containers {
        # Placeholder until the deploy-dev workflow pushes the real image. Terraform
        # ignores the image after creation, so deploys and applies do not fight.
        image = "us-docker.pkg.dev/cloudrun/container/job:latest"
        args  = each.value.args

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        dynamic "env" {
          for_each = each.value.secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }

        volume_mounts {
          name       = "app"
          mount_path = local.mount_path
        }
      }

      volumes {
        name = "app"
        gcs {
          bucket    = google_storage_bucket.app.name
          read_only = false
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  # Cloud Run checks at creation that the job's identity can read its secrets.
  depends_on = [
    google_secret_manager_secret_iam_member.runtime_reads_webhook,
    google_storage_bucket_iam_member.runtime_app,
  ]
}

# The scheduler signs in as the runtime account, which may only start these jobs.
resource "google_cloud_run_v2_job_iam_member" "runtime_runs" {
  for_each = google_cloud_run_v2_job.job

  name     = each.value.name
  location = each.value.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.runtime_sa}"
}

resource "google_cloud_scheduler_job" "job" {
  for_each = local.jobs

  name             = each.key
  region           = var.region
  schedule         = each.value.schedule
  time_zone        = var.time_zone
  attempt_deadline = "60s"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.job[each.key].id}:run"

    oauth_token {
      service_account_email = local.runtime_sa
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.runtime_runs]
}
