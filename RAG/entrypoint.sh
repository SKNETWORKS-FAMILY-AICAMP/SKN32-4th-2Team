#!/bin/bash
set -e

# 진짜 "최초 1회"만 필요한 작업 (예: 초기 관리자 계정, 초기 데이터)
FLAG_FILE="/app/.initialized"
if [ ! -f "$FLAG_FILE" ]; then
    echo "최초 세팅 실행..."
    python scripts/bootstrap_documents.py
    python scripts/bootstrap_documents.py --apply
    touch "$FLAG_FILE"
fi

exec python app.py