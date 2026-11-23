# AWS account audit trail

Turns on CloudTrail for the whole account and turns the events that matter into CloudWatch metrics, so the alert job can watch the platform, not only its own function.

- **Trail:** `platform-audit`, multi-region, with log file validation. Files go to the `platform-audit-trail-<account>` bucket (kept 365 days) and to the `/aws/cloudtrail/platform-audit` log group (kept 90 days).
- **Audit metrics** (`audit.tf`), in the `PlatformAudit` namespace: root use or a sign-in without MFA, IAM or Organizations changes, access keys created, the trail or its log group changed, something opened to the public, changes outside the home region, and KMS keys disabled or scheduled for deletion. `terraform/aws/dev` reads each one and alerts on any count above zero.

The first copy of management events is free. The 7 metrics fit in the free 10 custom metrics, and log ingestion is a few cents a month at this account's volume.

Apply this from your machine, not from GitHub: it changes account-wide logging, which the GitHub roles are not allowed to do.

```bash
cd terraform/aws/org
aws sso login --profile YOUR_PROFILE
export AWS_PROFILE=YOUR_PROFILE
terraform init -backend-config="bucket=slack-anomaly-dev-seed-tfstate"
terraform apply
```

Apply SEED first, because the state lives in its bucket.
