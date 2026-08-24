from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from ..core.database import Base


class Chatroom(Base):
    __tablename__ = "chatroom"

    chatroom_id = Column(String(36), primary_key=True)
    user_id = Column(String(20), ForeignKey("user.user_id"), nullable=False)
    chatroom_name = Column(String(100), nullable=False, default="새 대화")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)


class Chat(Base):
    __tablename__ = "chat"

    chat_id = Column(Integer, primary_key=True, autoincrement=True)
    chatroom_id = Column(String(36), ForeignKey("chatroom.chatroom_id"), nullable=False)
    speaker = Column(Enum("user", "llm", name="speaker_enum"), nullable=False)
    message = Column(Text, nullable=False)
    topic = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ChatSource(Base):
    """채팅 답변(llm) 하단에 표시되는 근거 문서 목록. chat 1건(llm 응답) : 근거 문서 N건.

    doc_id는 document.doc_id를 참조하는 값이지만, 외부 Chat API가 내려주는 값을 그대로
    저장하는 구조라 강한 FK로 묶지 않는다 (두 시스템 간 문서 ID 동기화가 어긋나도 채팅
    저장 자체가 실패하지 않도록). file_name/page는 응답 시점의 스냅샷이라, 이후 원본
    문서가 바뀌거나 삭제되어도 그때 보여줬던 근거 표시는 그대로 남는다."""

    __tablename__ = "chat_source"

    source_id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, ForeignKey("chat.chat_id"), nullable=False)
    doc_id = Column(Integer, nullable=True)
    file_name = Column(String(255), nullable=False)
    page = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
