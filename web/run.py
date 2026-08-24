"""Django 개발 서버 시작 파일입니다."""

import os
import sys

# 프로젝트 루트 디렉토리를 Python 경로에 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Django 설정 모듈 지정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Django 실행
from django.core.management import execute_from_command_line

if __name__ == "__main__":
    execute_from_command_line(['manage.py', 'runserver', '0.0.0.0:8000'])
