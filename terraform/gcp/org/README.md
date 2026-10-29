# GCP org metrics scope

Adds every active project in the org to the metrics scope of `slack-anomaly-dev`, so the job can read metrics from the whole org through one project. Projects directly under the org and under its top-level folders are included.

Apply this from your machine, not from GitHub. Adding a project to a metrics scope needs Monitoring Admin on both projects, and the GitHub service accounts do not get org-wide roles. Project owners already have it.

```bash
cd terraform/gcp/org
gcloud auth application-default login
terraform init -backend-config="bucket=slack-anomaly-dev-seed-tfstate"
terraform apply
```

Apply SEED first, because the state lives in its bucket. Re-apply when a project is added to the org. To leave a project out, add it to `exclude_projects`.
