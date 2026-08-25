"""서비스 전역 예외.

`message` 는 프론트가 그대로 출력할 수 있는 한국어여야 한다 (docs/API.md 6절).
"""

from __future__ import annotations


class LLMServiceError(Exception):
    error_code = "INTERNAL_ERROR"
    status_code = 500
    message = "일시적인 오류입니다. 잠시 후 다시 시도해주세요."

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.message = message
        super().__init__(self.message)


class ProviderTimeout(LLMServiceError):
    """15초 안에 응답하지 못하면 재시도 가능한 안내를 반환한다."""

    error_code = "LLM_TIMEOUT"
    status_code = 504
    message = "일시적인 오류입니다. 잠시 후 다시 시도해주세요."


class ProviderUnavailable(LLMServiceError):
    error_code = "LLM_UNAVAILABLE"
    status_code = 503
    message = "AI 응답 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."


class ProviderRateLimited(LLMServiceError):
    """벤더 API 호출 한도 초과.

    일반 장애(`LLM_UNAVAILABLE`)와 구분한다. 이건 **기다리면 풀리는** 실패라
    호출자가 얼마나 기다려야 하는지 알면 재시도 전략을 세울 수 있다.
    (Gemini 무료 티어는 분당 20회)

    서비스 자체는 재시도하지 않는다. 벤더가 알려주는 대기 시간이 보통 30초 이상이라
    요청 타임아웃(기본 15초) 안에 처리할 수 없다. 바로 429 를 돌려주고 판단은
    호출자에게 맡긴다.
    """

    error_code = "LLM_RATE_LIMITED"
    status_code = 429
    message = "요청이 많아 잠시 후 다시 시도해주세요."

    def __init__(self, message: str | None = None, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class ProviderNotConfigured(LLMServiceError):
    error_code = "PROVIDER_NOT_CONFIGURED"
    status_code = 503
    message = "AI 응답 서비스가 아직 설정되지 않았습니다. 관리자에게 문의해주세요."
