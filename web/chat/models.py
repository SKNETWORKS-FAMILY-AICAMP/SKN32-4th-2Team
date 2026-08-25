from django.db import models
from users.models import User


class Chatroom(models.Model):
    chatroom_id = models.CharField(max_length=36, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', to_field='username')
    chatroom_name = models.CharField(max_length=100, default="새 대화", null=False)
    created_at = models.DateTimeField(auto_now_add=True, null=False)
    is_deleted = models.BooleanField(default=False, null=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'chatroom'


class Chat(models.Model):
    SPEAKER_CHOICES = [
        ('user', 'User'),
        ('llm', 'LLM'),
    ]

    chat_id = models.AutoField(primary_key=True)
    chatroom = models.ForeignKey(Chatroom, on_delete=models.CASCADE, db_column='chatroom_id')
    speaker = models.CharField(max_length=4, choices=SPEAKER_CHOICES, null=False)
    message = models.TextField(null=False)
    topic = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=False)

    class Meta:
        db_table = 'chat'


class ChatSource(models.Model):
    """채팅 답변(llm) 하단에 표시되는 근거 문서 목록. chat 1건(llm 응답) : 근거 문서 N건.

    doc_id는 document.doc_id를 참조하는 값이지만, 외부 Chat API가 내려주는 값을 그대로
    저장하는 구조라 강한 FK로 묶지 않는다 (두 시스템 간 문서 ID 동기화가 어긋나도 채팅
    저장 자체가 실패하지 않도록). file_name/page는 응답 시점의 스냅샷이라, 이후 원본
    문서가 바뀌거나 삭제되어도 그때 보여줬던 근거 표시는 그대로 남는다."""

    source_id = models.AutoField(primary_key=True)
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, db_column='chat_id')
    doc_id = models.IntegerField(null=True, blank=True)
    file_name = models.CharField(max_length=255, null=False)
    page = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=False)

    class Meta:
        db_table = 'chat_source'
