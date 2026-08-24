"""PyCharm에서 직접 실행하는 FastAPI 시작 파일입니다."""

# ASGI 서버 실행을 위해 uvicorn을 가져옵니다.
import uvicorn

# 현재 파일이 직접 실행된 경우인지 확인합니다.
if __name__ == "__main__":
    # app.main 모듈의 app 객체를 개발 서버로 실행합니다.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
