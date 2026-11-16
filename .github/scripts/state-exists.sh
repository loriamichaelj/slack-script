#!/usr/bin/env bash
# Exit 0 if the root's Terraform state object exists. The read-only planner uses this
# to plan against an empty state when a root has never been applied.
#   state-exists.sh CLOUD BUCKET ROOT
set -euo pipefail
cloud="${1:?cloud}" bucket="${2:?bucket}" root="${3:?root}"

case "$cloud" in
  gcp) gcloud storage objects describe "gs://${bucket}/${root}/default.tfstate" >/dev/null 2>&1 ;;
  aws) aws s3api head-object --bucket "$bucket" --key "${root}/terraform.tfstate" >/dev/null 2>&1 ;;
  *)   echo "unsupported cloud: $cloud" >&2; exit 2 ;;
esac
