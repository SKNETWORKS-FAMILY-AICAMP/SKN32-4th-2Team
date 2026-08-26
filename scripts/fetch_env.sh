#!/bin/bash
set -e
SERVICE=$1
OUT_FILE="${SERVICE^^}/.env"

aws ssm get-parameters-by-path \
  --path "/SKN32-4th-2Team/${SERVICE}" \
  --recursive \
  --with-decryption \
  --query "Parameters[]" \
  --output json | \
jq -r '.[] | "\(.Name | split("/") | last)=\(.Value)"' > "$OUT_FILE"

echo "Generated $OUT_FILE"