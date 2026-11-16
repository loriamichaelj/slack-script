#!/usr/bin/env bash
# Builds the Azure Functions zip: the function entry point, this package, its dependencies
# and config/actions.yaml. Dependencies go in .python_packages, where the Functions host
# looks for them.
#
#   scripts/build-function.sh [OUTPUT_ZIP]      default: build/function.zip
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-$root/build/function.zip}"
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac
case "$out" in *.zip) ;; *) echo "output must end in .zip" >&2; exit 2 ;; esac
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

# Flex Consumption runs Linux on x86_64 with Python 3.12, whatever machine builds this.
python3 -m pip install --quiet --no-cache-dir \
  --target "$stage/.python_packages/lib/site-packages" \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: \
  "PyYAML>=6" "azure-functions>=1.20" "azure-identity>=1.15" \
  "azure-monitor-query>=1.3,<2" "azure-storage-blob>=12.19"

cp "$root/serverless/azure/function_app.py" "$root/serverless/azure/host.json" "$stage/"
cp -R "$root/src/anomaly_alerts" "$stage/anomaly_alerts"
mkdir -p "$stage/config"
cp "$root/config/actions.yaml" "$stage/config/actions.yaml"

find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +

mkdir -p "$(dirname "$out")"
rm -f "$out"
(cd "$stage" && zip -q -r -X "$out" .)
echo "built $out ($(du -h "$out" | cut -f1))"
