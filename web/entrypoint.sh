#!/bin/bash
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 진짜 "최초 1회"만 필요한 작업 (예: 초기 관리자 계정, 초기 데이터)
FLAG_FILE="/app/.initialized"
if [ ! -f "$FLAG_FILE" ]; then
    echo "최초 세팅 실행..."
    touch "$FLAG_FILE"
fi

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120