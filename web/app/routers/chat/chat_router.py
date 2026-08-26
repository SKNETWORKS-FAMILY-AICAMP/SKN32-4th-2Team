import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ...core.security import require_login, require_login_api
from ...core.database import get_db
from ...services.chat_service import (
    ChatServiceError,
    create_chatroom,
    delete_chatroom,
    get_messages,
    get_owned_chatroom,
    list_chatrooms,
    send_message,
)

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@router.get("/api/rooms")
def list_rooms_api(request: Request, db: Session = Depends(get_db)):
    user = require_login_api(request)
    return {"items": list_chatrooms(db, user["user_id"])}


@router.post("/api/rooms")
def create_room_api(request: Request, db: Session = Depends(get_db)):
    user = require_login_api(request)
    chatroom = create_chatroom(db, user["user_id"])
    return {
        "chatroom_id": chatroom.chatroom_id,
        "chatroom_name": chatroom.chatroom_name,
    }


@router.get("/api/rooms/{chatroom_id}/messages")
def get_messages_api(request: Request, chatroom_id: str, db: Session = Depends(get_db)):
    user = require_login_api(request)

    try:
        items = get_messages(db, chatroom_id, user["user_id"])
    except ChatServiceError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.message})

    return {"items": items}


@router.post("/api/rooms/{chatroom_id}/messages")
def send_message_api(
    request: Request,
    chatroom_id: str,
    message: str = Form(...),
    db: Session = Depends(get_db),
):
    user = require_login_api(request)

    try:
        reply = send_message(db, chatroom_id, user["user_id"], message)
    except ChatServiceError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.message})

    # 상태값과 sources/rag_degraded는 DB에 저장하지 않고 현재 응답의 화면 처리에만 쓴다.
    return {
        "message": reply["answer"],
        "answer_status": reply["answer_status"],
        "clarification_question": reply["clarification_question"],
        "sources": reply["sources"],
        "rag_degraded": reply["rag_degraded"],
    }


@router.delete("/api/rooms/{chatroom_id}")
def delete_room_api(request: Request, chatroom_id: str, db: Session = Depends(get_db)):
    user = require_login_api(request)

    try:
        delete_chatroom(db, chatroom_id, user["user_id"])
    except ChatServiceError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.message})

    return {"detail": "삭제되었습니다."}


@router.get("", response_class=HTMLResponse)
@router.get("/{chatroom_id}", response_class=HTMLResponse)
def chat_page(
    request: Request, chatroom_id: str | None = None, db: Session = Depends(get_db)
):
    """방 ID가 없으면(=/chat) 새 대화를 시작할 수 있는 빈 상태로 렌더링하고,
    방 ID가 있으면(=/chat/{chatroom_id}) 그 대화 내용을 이어서 보여준다.
    실제 채팅방(chatroom row)은 이 페이지 진입 시점이 아니라, 첫 메시지를 보낼 때
    (POST /chat/api/rooms/{chatroom_id}/messages 이전에 방 생성이 선행) 만들어진다."""
    user, redirect = require_login(request)
    if redirect:
        return redirect

    chatroom_name = "새 대화"

    if chatroom_id:
        try:
            chatroom = get_owned_chatroom(db, chatroom_id, user["user_id"])
        except ChatServiceError:
            return RedirectResponse(url="/chat", status_code=303)
        chatroom_name = chatroom.chatroom_name

    return templates.TemplateResponse(
        request,
        "chat/chat.html",
        {
            "user": user,
            "active": "chat_list" if chatroom_id else "chat_new",
            "chatroom_id": chatroom_id or "",
            "chatroom_name": chatroom_name,
        },
    )
