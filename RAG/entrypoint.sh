#!/bin/bash
set -e

VECTOR_STORE_DIR="/app/vector_store"

if [ -z "$(ls -A "$VECTOR_STORE_DIR" 2>/dev/null)" ]; then
    echo "vector_store 비어있음 - bootstrap 실행..."
    python scripts/bootstrap_documents.py
    python scripts/bootstrap_documents.py --apply
else
    echo "기존 vector_store 발견 - bootstrap 스킵"
fi

exec python app.py