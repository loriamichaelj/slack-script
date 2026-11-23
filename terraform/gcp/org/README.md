# GCP org metrics scope

Adds every active project in the org to the metrics scope of `slack-anomaly-dev`, so the job can read metrics from the whole org through one project. Projects directly under the org and under its top-level folders are included.

Apply this from your machine, not from GitHub. Adding a project to a metrics scope needs Monitoring Admin on both projects, and the GitHub service accounts do not get org-wide roles. Project owners already have it.

```bash
cd terraform/gcp/org
gcloud auth application-default login
terraform init -backend-config="bucket=slack-anomaly-dev-seed-tfstate"
terraform apply
```

It also sets up org-wide logs and traces in the same project:

- **Logs:** an organization sink copies every log entry from every org project, including projects created later, into the `org-logs` bucket (30 days, Log Analytics on). Query it in Logs Explorer or Log Analytics. Copies are billed at ingestion again, beyond the free 50 GiB per project per month.
- **Traces:** the `org` trace scope lists every org project so Trace Explorer can search them all. Traces stay in their own projects.

Creating an organization sink needs Logs Configuration Writer at the org level, which Organization Admin does not include:

```bash
gcloud organizations add-iam-policy-binding 618554946741 \
  --member=user:YOUR_EMAIL --role=roles/logging.configWriter
```

Terraform cannot make the trace scope the default. After the apply:

```bash
gcloud observability scopes update _Default --location=global \
  --trace-scope=projects/slack-anomaly-dev/locations/global/traceScopes/org --project=slack-anomaly-dev
```

It also gives `anomaly-runtime` read-only access to each billing account's export dataset (`billing_datasets`), which live in other org projects.

Platform signals the alert job reads from the scoping project:

- **Audit events** (`audit.tf`): log-based metrics on the `org-logs` bucket, one per event that matters every time: IAM or org policy changes, service account keys created, logging changed, something made public, new projects or APIs, KMS keys destroyed. Each is split by the project it came from, and any count above zero alerts.
- **Uptime** (`uptime.tf`): an HTTPS check of each site in `uptime_hosts` every 5 minutes from 3 regions.

Projects outside the org (they have no organization parent) are not covered by the sink, the scope or the audit metrics. Move them into the org to cover them.

Apply SEED first, because the state lives in its bucket. Re-apply when a project is added to the org. To leave a project out, add it to `exclude_projects`.
