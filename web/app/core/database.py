import os
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

# 운영 환경에서는 MySQL 8.0 연결 문자열을 환경변수로 주입한다.
DATABASE_URL = os.getenv("DATABASE_URL")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def warm_up() -> None:
    """서버 시작 시 커넥션 풀에 연결을 하나 미리 맺어둔다.

    DB는 로그인/조회/채팅 저장 등 거의 모든 기능이 의존하는 필수 자원이라
    Chat API 워밍업과 달리 여기서는 예외를 삼키지 않는다 - DB가 아예 연결이 안 되는
    상태라면, 첫 요청에서 뒤늦게 실패하는 것보다 서버 기동 자체를 실패시키는 게 낫다."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
