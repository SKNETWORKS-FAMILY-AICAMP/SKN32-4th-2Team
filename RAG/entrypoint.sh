#!/bin/bash
set -e

# 진짜 "최초 1회"만 필요한 작업 (예: 초기 관리자 계정, 초기 데이터)
FLAG_FILE="/app/.initialized"
if [ ! -f "$FLAG_FILE" ]; then
    echo "최초 세팅 실행..."
    python scripts/bootstrap_documents.py
    # createsuperuser는 대화형이라 별도 처리 (아래 참고)
    touch "$FLAG_FILE"
fi

exec python app.py