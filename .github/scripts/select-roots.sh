#!/usr/bin/env bash
# Prints the Terraform roots a workflow should act on, as a JSON array of
# .github/terraform-roots.json entries.
#
#   select-roots.sh all             every root
#   select-roots.sh changed         roots whose directory changed between $BEFORE and $GITHUB_SHA
#   select-roots.sh target CLOUD/ROOT   one root, for example gcp/seed
#
# ONLY_READY=1 drops roots of a cloud that is not bootstrapped yet, so no job (and no
# environment approval) is started for them. A cloud counts as bootstrapped once its
# repository variable is set: GCP_WORKLOAD_IDENTITY_PROVIDER, AWS_ACCOUNT_ID, or
# AZURE_TENANT_ID together with AZURE_SUBSCRIPTION_ID.
#
# FOR_APPLY=1 drops roots that are planned in CI but applied by hand ("apply": false).
set -euo pipefail

registry="$(cd "$(dirname "$0")/.." && pwd)/terraform-roots.json"
mode="${1:?usage: select-roots.sh all|changed|target [CLOUD/ROOT]}"
zeros=0000000000000000000000000000000000000000

case "$mode" in
  all)
    roots=$(jq -c . "$registry")
    ;;
  target)
    roots=$(jq -c --arg t "${2:?target needs CLOUD/ROOT}" '[.[] | select(.cloud + "/" + .root == $t)]' "$registry")
    ;;
  changed)
    before="${BEFORE:-}"
    if [ -z "$before" ] || [ "$before" = "$zeros" ]; then
      roots=$(jq -c . "$registry")  # no base to compare with: consider every root changed
    else
      roots=$(
        jq -c '.[]' "$registry" | while read -r entry; do
          dir="terraform/$(jq -r '.cloud + "/" + .root' <<<"$entry")"
          if ! git diff --quiet "$before" "${GITHUB_SHA:-HEAD}" -- "$dir"; then
            echo "$entry"
          fi
        done | jq -sc .
      )
    fi
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 2
    ;;
esac

if [ "${FOR_APPLY:-}" = "1" ]; then
  roots=$(jq -c '[.[] | select(.apply != false)]' <<<"$roots")
fi

if [ "${ONLY_READY:-}" = "1" ]; then
  ready=$(jq -c \
    --arg gcp "${GCP_WORKLOAD_IDENTITY_PROVIDER:-}" \
    --arg aws "${AWS_ACCOUNT_ID:-}" \
    --arg az_tenant "${AZURE_TENANT_ID:-}" \
    --arg az_subscription "${AZURE_SUBSCRIPTION_ID:-}" \
    '[.[] | select(
        (.cloud == "gcp" and $gcp != "") or
        (.cloud == "aws" and $aws != "") or
        (.cloud == "azure" and $az_tenant != "" and $az_subscription != "")
      )]' <<<"$roots")
  if [ "$ready" != "$roots" ]; then
    echo "::notice::Skipped roots of clouds that are not bootstrapped yet (see terraform/<cloud>/seed/README.md)." >&2
  fi
  roots="$ready"
fi

echo "$roots"
