#!/usr/bin/env bash
# Builds the AWS Lambda zip: this package, its dependencies and config/actions.yaml.
# boto3 is already in the Lambda runtime, so it is left out.
#
#   scripts/build-lambda.sh [OUTPUT_ZIP]      default: build/lambda.zip
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-$root/build/lambda.zip}"
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac
case "$out" in *.zip) ;; *) echo "output must end in .zip" >&2; exit 2 ;; esac
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

# Lambda runs Linux on x86_64 with Python 3.12, whatever machine builds this.
python3 -m pip install --quiet --no-cache-dir --target "$stage" \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: \
  "PyYAML>=6"

cp -R "$root/src/anomaly_alerts" "$stage/anomaly_alerts"
mkdir -p "$stage/config"
cp "$root/config/actions.yaml" "$stage/config/actions.yaml"

find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$stage" -name '*.dist-info' -type d -prune -exec rm -rf {} +

mkdir -p "$(dirname "$out")"
rm -f "$out"
(cd "$stage" && zip -q -r -X "$out" .)
echo "built $out ($(du -h "$out" | cut -f1))"
