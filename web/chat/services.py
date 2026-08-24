"""Chat API 연동 지점.

.env의 CHAT_API_BASE_URL로 지정된 서버와 통신한다.
인터페이스 명세:
  POST {base}/v1/chat            - 질문 -> 답변/주제/근거문서
  POST {base}/v1/chatroom-name   - 첫 질문 -> 채팅방 제목
  GET  {base}/health             - 서버 상태 (현재 라우트에서는 미사용, 필요 시 사용)

에러 응답은 다음 형태로 통일되어 있다: {"error_code": "...", "message": "..."}
error_code는 아래 5개가 전부이며, message는 그대로 화면에 출력해도 되는 한국어 문구다.
"""

import atexit
import os
import threading

import httpx

from django.conf import settings

def get_chat_api_base_url():
    """Get CHAT_API_BASE_URL from settings, handling the case where settings might not be fully initialized."""
    if settings.CHAT_API_BASE_URL:
        return settings.CHAT_API_BASE_URL.rstrip("/")
    return ""

def get_chat_api_timeout():
    """Get CHAT_API_TIMEOUT_SECONDS from settings with a default fallback."""
    return float(getattr(settings, 'CHAT_API_TIMEOUT_SECONDS', 15))

_CONNECT_TIMEOUT = 5.0

_DEFAULT_MESSAGE = "일시적인 오류입니다. 잠시 후 다시 시도해주세요."


class ChatAPIError(Exception):
    """Chat API 호출 실패. message는 프론트에 그대로 노출해도 되는 한국어 문구다."""

    def __init__(
        self, message: str, status_code: int = 500, error_code: str = "INTERNAL_ERROR"
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


_client_lock = threading.Lock()
_client_instance: httpx.Client | None = None


def _client() -> httpx.Client:
    global _client_instance

    chat_api_base_url = get_chat_api_base_url()
    if not chat_api_base_url:
        # 서버 설정 문제이므로, 명세의 PROVIDER_NOT_CONFIGURED와 동일한 취급을 한다.
        raise ChatAPIError(
            "AI 응답 서비스가 아직 설정되지 않았습니다. 관리자에게 문의해주세요.",
            status_code=503,
            error_code="PROVIDER_NOT_CONFIGURED",
        )

    if _client_instance is None:
        with _client_lock:
            if (
                _client_instance is None
            ):  # double-checked locking: 락 대기 중 이미 만들어졌을 수 있음
                _client_instance = httpx.Client(
                    base_url=chat_api_base_url,
                    timeout=httpx.Timeout(
                        connect=_CONNECT_TIMEOUT,
                        read=get_chat_api_timeout(),
                        write=get_chat_api_timeout(),
                        pool=get_chat_api_timeout(),
                    ),
                    # 로컬/사내망의 지정된 서버만 호출하므로 OS 프록시 자동감지가 필요 없다.
                    # trust_env=True(기본값)로 두면 환경에 따라 초기화가 느려지는 경우가 있어 꺼둔다.
                    trust_env=False,
                )

    return _client_instance


@atexit.register
def _close_shared_client() -> None:
    """프로세스 종료 시 커넥션을 정리한다 (best-effort; 실패해도 무시)."""
    if _client_instance is not None:
        try:
            _client_instance.close()
        except Exception:
            pass


def warm_up() -> None:
    """서버 시작 시(lifespan) 미리 호출해서 httpx.Client 생성 비용을 첫 요청 전에 미리 낸다.
    CHAT_API_BASE_URL이 아직 설정 안 된 환경(예: 채팅 기능 붙이기 전)에서도 서버 자체는
    떠야 하므로, PROVIDER_NOT_CONFIGURED는 호출한 쪽에서 잡아서 넘어가면 된다."""
    _client()


def _raise_from_error_response(res: httpx.Response) -> None:
    """{error_code, message} 형태의 에러 응답을 ChatAPIError로 변환한다."""
    try:
        body = res.json()
        message = body.get("message") or _DEFAULT_MESSAGE
        error_code = body.get("error_code") or "INTERNAL_ERROR"
    except ValueError:
        message = _DEFAULT_MESSAGE
        error_code = "INTERNAL_ERROR"

    raise ChatAPIError(message, status_code=res.status_code, error_code=error_code)


def _post(path: str, payload: dict) -> dict:
    # 주의: _client()가 반환하는 건 프로세스 전체가 공유하는 인스턴스이므로
    # `with _client() as client:` 처럼 컨텍스트 매니저로 쓰면 요청이 끝날 때 그 클라이언트를
    # close()해버려서 다음 요청이 깨진다. 그래서 그냥 변수로만 받아서 쓰고 닫지 않는다
    # (종료는 위의 _close_shared_client에서 프로세스 종료 시 한 번만 처리).
    client = _client()

    try:
        res = client.post(path, json=payload)
    except httpx.TimeoutException:
        raise ChatAPIError(
            "일시적인 오류입니다. 잠시 후 다시 시도해주세요.",
            status_code=504,
            error_code="LLM_TIMEOUT",
        )
    except httpx.RequestError:
        # 연결 자체가 안 되는 경우 (DNS 실패, 연결 거부 등)
        raise ChatAPIError(
            "AI 응답 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.",
            status_code=503,
            error_code="LLM_UNAVAILABLE",
        )

    if res.status_code >= 400:
        _raise_from_error_response(res)

    try:
        return res.json()
    except ValueError:
        raise ChatAPIError(
            _DEFAULT_MESSAGE, status_code=500, error_code="INTERNAL_ERROR"
        )


def get_chat_completion(
    chatroom_id: str, message: str, history: list[dict] | None = None
) -> dict:
    """POST /v1/chat 호출.

    반환: {"answer": str, "topic": str, "sources": list[dict], "rag_degraded": bool}
    """
    payload = {"chatroom_id": chatroom_id, "message": message}
    if history:
        payload["history"] = history

    data = _post("/v1/chat", payload)

    return {
        "answer": data.get("answer", ""),
        "topic": data.get("topic"),
        "sources": data.get("sources") or [],
        "rag_degraded": bool(data.get("rag_degraded", False)),
    }


def generate_chatroom_name(message: str) -> str:
    """POST /v1/chatroom-name 호출. 새 채팅방 첫 질문 때 한 번만 호출한다."""
    data = _post("/v1/chatroom-name", {"message": message})
    return data.get("name") or message[:30]


def check_health() -> dict:
    """GET /health 호출. 현재 어떤 라우트에서도 사용하지 않지만, 상태 점검용으로 미리 준비해둔다."""
    client = _client()
    try:
        res = client.get("/health")
    except httpx.TimeoutException:
        raise ChatAPIError(_DEFAULT_MESSAGE, status_code=504, error_code="LLM_TIMEOUT")
    except httpx.RequestError:
        raise ChatAPIError(
            "AI 응답 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.",
            status_code=503,
            error_code="LLM_UNAVAILABLE",
        )

    if res.status_code >= 400:
        _raise_from_error_response(res)

    return res.json()
