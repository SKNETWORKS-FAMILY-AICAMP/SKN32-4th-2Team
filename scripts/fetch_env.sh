#!/bin/bash
set -e
SERVICE=$1   # 실행 시 인자: web, rag, llm (소문자로 통일해서 호출)

case "$SERVICE" in
  web) FOLDER="web" ;;
  rag) FOLDER="RAG" ;;
  llm) FOLDER="LLM" ;;
  *) echo "Unknown service: $SERVICE"; exit 1 ;;
esac

OUT_FILE="${FOLDER}/.env"

aws ssm get-parameters-by-path \
  --path "/SKN32-4th-2Team/${SERVICE}" \
  --recursive \
  --with-decryption \
  --query "Parameters[]" \
  --output json | \
jq -r '.[] | "\(.Name | split("/") | last)=\(.Value)"' > "$OUT_FILE"

echo "Generated $OUT_FILE"