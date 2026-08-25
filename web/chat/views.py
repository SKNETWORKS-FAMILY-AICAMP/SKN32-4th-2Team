import uuid
from concurrent.futures import ThreadPoolExecutor
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Chatroom, Chat, ChatSource
from .services import ChatAPIError, generate_chatroom_name, get_chat_completion
from users.views import post_login_redirect_url

# 명세: "이전 대화 3건" - 질문-응답을 한 쌍으로 보고, 최근 3쌍(=최대 6개 메시지)을 전달한다.
HISTORY_PAIRS = 3


class ChatServiceError(Exception):
    """대화방/메시지 처리 중 발생하는 오류. 라우터에서 status_code로 매핑해서 응답한다."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_chatroom(user_id):
    chatroom = Chatroom(chatroom_id=str(uuid.uuid4()), user_id=user_id)
    chatroom.save()
    return chatroom


def list_chatrooms(user_id):
    rooms = Chatroom.objects.filter(user_id=user_id, is_deleted=False).order_by('-created_at')
    return [
        {
            'chatroom_id': room.chatroom_id,
            'chatroom_name': room.chatroom_name,
            'created_at': room.created_at.strftime('%Y-%m-%d %H:%M') if room.created_at else '',
        }
        for room in rooms
    ]


def get_owned_chatroom(chatroom_id, user_id):
    """대화방을 조회하고, 존재/소유자 여부를 함께 검증한다. 타 사용자의 대화방 접근을 차단한다."""
    try:
        chatroom = Chatroom.objects.get(chatroom_id=chatroom_id)
    except Chatroom.DoesNotExist:
        raise ChatServiceError("대화방을 찾을 수 없습니다.", status_code=404)
    
    if chatroom.is_deleted or chatroom.user_id != user_id:
        raise ChatServiceError("대화방을 찾을 수 없습니다.", status_code=404)
    return chatroom


def get_messages(chatroom_id, user_id):
    get_owned_chatroom(chatroom_id, user_id)
    
    chats = Chat.objects.filter(chatroom_id=chatroom_id).order_by('chat_id')
    llm_chat_ids = [chat.chat_id for chat in chats if chat.speaker == 'llm']
    sources_by_chat_id = {}
    
    if llm_chat_ids:
        sources = ChatSource.objects.filter(chat_id__in=llm_chat_ids).order_by('source_id')
        for source in sources:
            sources_by_chat_id.setdefault(source.chat_id, []).append({
                'doc_id': source.doc_id,
                'original_file_name': source.file_name,
                'page': source.page,
            })
    
    return [
        {
            'speaker': chat.speaker,
            'message': chat.message,
            'created_at': chat.created_at.strftime('%Y-%m-%d %H:%M') if chat.created_at else '',
            'sources': sources_by_chat_id.get(chat.chat_id, []),
        }
        for chat in chats
    ]


def _recent_history(chatroom_id, pairs=HISTORY_PAIRS):
    """이 채팅방의 가장 최근 질문-응답 N쌍을 시간순(오래된 것 -> 최신)으로 반환한다.
    지금 막 들어온 사용자 질문을 저장하기 '전'에 호출해야 한다."""
    recent = Chat.objects.filter(chatroom_id=chatroom_id).order_by('-chat_id')[:pairs * 2]
    return [{'speaker': chat.speaker, 'message': chat.message} for chat in reversed(recent)]


def _save_error_turn(chatroom_id, message, error):
    """에러가 나도 대화 이력은 온전히 남긴다: 사용자 질문(topic=에러) + llm 쪽엔 에러 안내 문구.
    재접속해서 대화방을 다시 열어도 "다시 시도해주세요" 문구가 그대로 보이게 된다."""
    Chat.objects.create(chatroom_id=chatroom_id, speaker='user', message=message, topic='에러')
    Chat.objects.create(chatroom_id=chatroom_id, speaker='llm', message=error.message)


def send_message(chatroom_id, user_id, message):
    """사용자 메시지를 저장하고, Chat API로 답변을 생성해 저장한 뒤 화면 표시용 데이터를 반환한다.

    반환: {"answer": str, "sources": list[dict], "rag_degraded": bool}
    """
    chatroom = get_owned_chatroom(chatroom_id, user_id)
    
    message = message.strip()
    if not message:
        raise ChatServiceError("메시지를 입력해주세요.")
    
    history = _recent_history(chatroom_id)
    is_first_message = chatroom.chatroom_name == "새 대화"
    
    if is_first_message:
        # 첫 메시지일 때만 두 요청을 동시에 던져서 순차 실행 시 더해지던 지연을 없앤다.
        with ThreadPoolExecutor(max_workers=2) as executor:
            chat_future = executor.submit(get_chat_completion, chatroom_id, message, history)
            name_future = executor.submit(generate_chatroom_name, message)
            
            try:
                result = chat_future.result()
            except ChatAPIError as e:
                _save_error_turn(chatroom_id, message, e)
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
            _save_error_turn(chatroom_id, message, e)
            raise ChatServiceError(e.message, status_code=e.status_code)
    
    chatroom.save()
    
    user_chat = Chat.objects.create(chatroom_id=chatroom_id, speaker='user', message=message, topic=result['topic'])
    
    llm_chat = Chat.objects.create(chatroom_id=chatroom_id, speaker='llm', message=result['answer'])
    
    for source in result['sources']:
        ChatSource.objects.create(
            chat=llm_chat,
            doc_id=source.get('doc_id'),
            file_name=source.get('original_file_name', ''),
            page=source.get('page'),
        )
    
    return {
        'answer': result['answer'],
        'sources': result['sources'],
        'rag_degraded': result['rag_degraded'],
    }


def delete_chatroom(chatroom_id, user_id):
    chatroom = get_owned_chatroom(chatroom_id, user_id)
    chatroom.is_deleted = True
    chatroom.deleted_at = timezone.now()
    chatroom.save()


@login_required
@require_http_methods(["GET"])
def list_rooms_api(request):
    return JsonResponse({'items': list_chatrooms(request.user.username)})


@login_required
@require_http_methods(["POST"])
def create_room_api(request):
    chatroom = create_chatroom(request.user.username)
    return JsonResponse({'chatroom_id': chatroom.chatroom_id, 'chatroom_name': chatroom.chatroom_name})


@login_required
@require_http_methods(["GET"])
def get_messages_api(request, chatroom_id):
    try:
        items = get_messages(chatroom_id, request.user.username)
    except ChatServiceError as e:
        return JsonResponse({'detail': e.message}, status=e.status_code)
    
    return JsonResponse({'items': items})


@login_required
@require_http_methods(["POST"])
def send_message_api(request, chatroom_id):
    message = request.POST.get('message', '')
    
    try:
        reply = send_message(chatroom_id, request.user.username, message)
    except ChatServiceError as e:
        return JsonResponse({'detail': e.message}, status=e.status_code)
    
    # reply = {"answer": str, "sources": list[dict], "rag_degraded": bool}
    # sources/rag_degraded는 DB에 저장하지 않고 화면 표시(근거 문서 영역, 저하 안내)에만 쓴다.
    return JsonResponse({
        'message': reply['answer'],
        'sources': reply['sources'],
        'rag_degraded': reply['rag_degraded'],
    })


@login_required
@require_http_methods(["DELETE"])
def delete_room_api(request, chatroom_id):
    try:
        delete_chatroom(chatroom_id, request.user.username)
    except ChatServiceError as e:
        return JsonResponse({'detail': e.message}, status=e.status_code)
    
    return JsonResponse({'detail': '삭제되었습니다.'})


@login_required
def chat_page(request, chatroom_id=None):
    """방 ID가 없으면(=/chat) 새 대화를 시작할 수 있는 빈 상태로 렌더링하고,
    방 ID가 있으면(=/chat/{chatroom_id}) 그 대화 내용을 이어서 보여준다.
    실제 채팅방(chatroom row)은 이 페이지 진입 시점이 아니라, 첫 메시지를 보낼 때
    (POST /chat/api/rooms/{chatroom_id}/messages 이전에 방 생성이 선행) 만들어진다."""
    chatroom_name = "새 대화"
    
    if chatroom_id:
        try:
            chatroom = get_owned_chatroom(chatroom_id, request.user.username)
            chatroom_name = chatroom.chatroom_name
        except ChatServiceError:
            return redirect('/chat')
    
    return render(request, 'chat/chat.html', {
        'user': request.user,
        'active': 'chat_list' if chatroom_id else 'chat_new',
        'chatroom_id': chatroom_id or '',
        'chatroom_name': chatroom_name,
    })
