import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import Chat, ChatSource, Chatroom
from .llm_client import ChatAPIError, generate_chatroom_name, get_chat_completion

# 명세: "이전 대화 3건" - 질문-응답을 한 쌍으로 보고, 최근 3쌍(=최대 6개 메시지)을 전달한다.
HISTORY_PAIRS = 3


class ChatServiceError(Exception):
    """대화방/메시지 처리 중 발생하는 오류. 라우터에서 status_code로 매핑해서 응답한다."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_chatroom(db: Session, user_id: str) -> Chatroom:
    chatroom = Chatroom(chatroom_id=str(uuid.uuid4()), user_id=user_id)
    db.add(chatroom)
    db.commit()
    db.refresh(chatroom)
    return chatroom


def list_chatrooms(db: Session, user_id: str) -> list[dict]:
    stmt = (
        select(Chatroom)
        .where(Chatroom.user_id == user_id, Chatroom.is_deleted == False)  # noqa: E712
        .order_by(desc(Chatroom.created_at))
    )
    rooms = db.scalars(stmt).all()

    return [
        {
            "chatroom_id": room.chatroom_id,
            "chatroom_name": room.chatroom_name,
            "created_at": room.created_at.strftime("%Y-%m-%d %H:%M") if room.created_at else "",
        }
        for room in rooms
    ]


def get_owned_chatroom(db: Session, chatroom_id: str, user_id: str) -> Chatroom:
    """대화방을 조회하고, 존재/소유자 여부를 함께 검증한다. 타 사용자의 대화방 접근을 차단한다."""

    chatroom = db.get(Chatroom, chatroom_id)
    if chatroom is None or chatroom.is_deleted or chatroom.user_id != user_id:
        raise ChatServiceError("대화방을 찾을 수 없습니다.", status_code=404)
    return chatroom


def get_messages(db: Session, chatroom_id: str, user_id: str) -> list[dict]:
    get_owned_chatroom(db, chatroom_id, user_id)

    stmt = select(Chat).where(Chat.chatroom_id == chatroom_id).order_by(Chat.chat_id)
    chats = db.scalars(stmt).all()

    llm_chat_ids = [chat.chat_id for chat in chats if chat.speaker == "llm"]
    sources_by_chat_id: dict[int, list[dict]] = {}
    if llm_chat_ids:
        src_stmt = (
            select(ChatSource)
            .where(ChatSource.chat_id.in_(llm_chat_ids))
            .order_by(ChatSource.source_id)
        )
        for source in db.scalars(src_stmt).all():
            sources_by_chat_id.setdefault(source.chat_id, []).append({
                "doc_id": source.doc_id,
                "original_file_name": source.file_name,
                "page": source.page,
            })

    return [
        {
            "speaker": chat.speaker,
            "message": chat.message,
            "created_at": chat.created_at.strftime("%Y-%m-%d %H:%M") if chat.created_at else "",
            "sources": sources_by_chat_id.get(chat.chat_id, []),
        }
        for chat in chats
    ]


def _recent_history(db: Session, chatroom_id: str, pairs: int = HISTORY_PAIRS) -> list[dict]:
    """이 채팅방의 가장 최근 질문-응답 N쌍을 시간순(오래된 것 -> 최신)으로 반환한다.
    지금 막 들어온 사용자 질문을 저장하기 '전'에 호출해야 한다."""

    stmt = (
        select(Chat)
        .where(Chat.chatroom_id == chatroom_id)
        .order_by(desc(Chat.chat_id))
        .limit(pairs * 2)
    )
    recent = db.scalars(stmt).all()

    return [{"speaker": chat.speaker, "message": chat.message} for chat in reversed(recent)]


def _save_error_turn(db: Session, chatroom_id: str, message: str, error: ChatAPIError) -> None:
    """에러가 나도 대화 이력은 온전히 남긴다: 사용자 질문(topic=에러) + llm 쪽엔 에러 안내 문구.
    재접속해서 대화방을 다시 열어도 "다시 시도해주세요" 문구가 그대로 보이게 된다."""
    db.add(Chat(chatroom_id=chatroom_id, speaker="user", message=message, topic="에러"))
    db.add(Chat(chatroom_id=chatroom_id, speaker="llm", message=error.message))
    db.commit()


def send_message(db: Session, chatroom_id: str, user_id: str, message: str) -> dict:
    """사용자 메시지를 저장하고, Chat API로 답변을 생성해 저장한 뒤 화면 표시용 데이터를 반환한다.

    반환: {"answer": str, "sources": list[dict], "rag_degraded": bool}
    """

    chatroom = get_owned_chatroom(db, chatroom_id, user_id)

    message = message.strip()
    if not message:
        raise ChatServiceError("메시지를 입력해주세요.")

    history = _recent_history(db, chatroom_id)
    is_first_message = chatroom.chatroom_name == "새 대화"

    if is_first_message:
        # 첫 메시지일 때만 두 요청을 동시에 던져서 순차 실행 시 더해지던 지연을 없앤다.
        with ThreadPoolExecutor(max_workers=2) as executor:
            chat_future = executor.submit(get_chat_completion, chatroom_id, message, history)
            name_future = executor.submit(generate_chatroom_name, message)

            try:
                result = chat_future.result()
            except ChatAPIError as e:
                _save_error_turn(db, chatroom_id, message, e)
                raise ChatServiceError(e.message, status_code=e.status_code)

            try:
                chatroom.chatroom_name = name_future.result()
            except ChatAPIError:
                # 제목 생성 실패는 대화 자체를 막을 이유가 없으므로, 조용히 기존 방식으로 대체한다.
                chatroom.chatroom_name = message[:30]
    else:
        try:
            result = get_chat_completion(chatroom_id, message, history)
        except ChatAPIError as e:
            _save_error_turn(db, chatroom_id, message, e)
            raise ChatServiceError(e.message, status_code=e.status_code)

    db.add(Chat(chatroom_id=chatroom_id, speaker="user", message=message, topic=result["topic"]))

    llm_chat = Chat(chatroom_id=chatroom_id, speaker="llm", message=result["answer"])
    db.add(llm_chat)
    db.flush()  # llm_chat.chat_id를 채우기 위해 (커밋 전에 FK로 참조해야 함)

    for source in result["sources"]:
        db.add(ChatSource(
            chat_id=llm_chat.chat_id,
            doc_id=source.get("doc_id"),
            file_name=source.get("original_file_name", ""),
            page=source.get("page"),
        ))

    db.commit()

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "rag_degraded": result["rag_degraded"],
    }


def delete_chatroom(db: Session, chatroom_id: str, user_id: str) -> None:
    chatroom = get_owned_chatroom(db, chatroom_id, user_id)
    chatroom.is_deleted = True
    chatroom.deleted_at = datetime.now()
    db.commit()