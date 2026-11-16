# CI/CD

GitHub Actions for this repo, the same on every cloud.

## Workflows

| File | Name | Runs | Does |
| --- | --- | --- | --- |
| `ci-tests.yml` | ci tests | pull request | `pytest` on Python 3.11 and 3.12 |
| `ci-security.yml` | ci security | pull request | Trivy and Checkov on `terraform/`, Trivy on dependencies and secrets |
| `tf-plan.yml` | tf plan | pull request touching `terraform/**` | read-only plan of every root, on every cloud |
| `tf-apply.yml` | tf apply | push to `dev`, or by hand | applies the roots that changed |
| `tf-destroy.yml` | tf destroy | by hand only | destroys one workload root |
| `deploy-gcp-dev.yml` | deploy gcp dev | app change, or after `tf apply` | builds the image and updates the Cloud Run jobs |
| `deploy-aws-dev.yml` | deploy aws dev | app change, or after `tf apply` | builds the Lambda zip and uploads it |

## Naming

- **Workflow files:** `<area>-<action>[-<cloud>-<env>].yml`. Areas are `ci` (checks), `tf` (Terraform, all clouds) and `deploy` (app releases, one per cloud and environment, such as `deploy-aws-dev.yml`).
- **Workflow `name:`** is the file name with spaces: `tf apply`, `deploy gcp dev`.
- **Job names** say what and where: `plan gcp/seed`, `apply aws/seed`.
- **Identities** have the same name on every cloud, as a GCP service account or an AWS role: `tf-planner` (read-only plan), `seed-admin` (applies seed roots), `dev-deployer` (applies and destroys dev roots), `anomaly-runtime` (the app at run time).
- **GitHub environments** are `CI` (plans and destroys, needs a reviewer), `SEED` (applies seed, needs a reviewer) and `DEV` (applies dev, `dev` branch only).
- **Repository variables** are `<CLOUD>_<THING>`: `GCP_WORKLOAD_IDENTITY_PROVIDER`, `AWS_ACCOUNT_ID`, and for Azure `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` and one client ID per identity (`AZURE_CLIENT_ID_TF_PLANNER`, `_SEED_ADMIN`, `_DEV_DEPLOYER`), because on Azure each identity is its own app registration. They are set once after that cloud's seed is applied, and they are also the switch that turns that cloud's workflows on.

## How it fits together

- `terraform-roots.json` lists every Terraform root the workflows manage: cloud, directory, the backend settings `terraform init` needs (a bucket, or an Azure storage account and container), GitHub environment and identities. It is the one place to add a root. A root marked `"apply": false` is planned in CI but applied by hand: `azure/seed` is, because it manages Entra app registrations and CI should not hold directory write rights.
- `scripts/select-roots.sh` turns that list into a job matrix: all roots, the ones a push changed, or one picked by hand. Roots of a cloud that is not bootstrapped are dropped before any job (or approval) starts.
- `actions/cloud-login` signs in with OIDC to GCP or AWS, with no stored keys. `actions/setup-terraform` pins the Terraform version in one place.
- `terraform/gcp/org` is not in the list. It is applied locally by an org admin.

## Safety defaults

Every action is pinned to a commit SHA, with the version in a comment. Dependabot opens a weekly PR to move them. Every job has a timeout and the narrowest `permissions` it needs, and only the jobs that sign in to a cloud get `id-token: write`. Plan and test runs cancel when a newer commit arrives, while apply and destroy queue per root and are never cancelled.

## Adding a root or a cloud

- **A new root on GCP or AWS:** add an entry to `terraform-roots.json`, and the workflows pick it up. For `tf apply` and `tf destroy`, also add it to that workflow's `options:` list.
- **A new cloud:** add a branch for it to `actions/cloud-login` and to the case statements in `scripts/state-exists.sh` and `scripts/select-roots.sh` (its readiness variables), then list its roots in the registry. Azure was added this way. `tests/test_ci_scripts.py` checks the registry and the selector.
