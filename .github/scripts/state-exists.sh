#!/usr/bin/env bash
# Exit 0 if the root's Terraform state object exists. The read-only planner uses this
# to plan against an empty state when a root has never been applied.
#   BACKEND='{"bucket": "..."}' state-exists.sh CLOUD ROOT
# BACKEND is the registry entry's "backend" object.
set -euo pipefail
cloud="${1:?cloud}" root="${2:?root}"
backend="${BACKEND:?BACKEND must hold the registry backend object}"
field() { jq -er --arg k "$1" '.[$k]' <<<"$backend"; }

case "$cloud" in
  gcp) gcloud storage objects describe "gs://$(field bucket)/${root}/default.tfstate" >/dev/null 2>&1 ;;
  aws) aws s3api head-object --bucket "$(field bucket)" --key "${root}/terraform.tfstate" >/dev/null 2>&1 ;;
  azure)
    [ "$(az storage blob exists --account-name "$(field storage_account_name)" \
      --container-name "$(field container_name)" --name "${root}.tfstate" \
      --auth-mode login --query exists -o tsv 2>/dev/null)" = "true" ]
    ;;
  *) echo "unsupported cloud: $cloud" >&2; exit 2 ;;
esac
