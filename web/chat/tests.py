from django.test import Client, TestCase

from chat.models import Chat, Chatroom, ChatSource
from chat.views import get_messages
from users.models import User


class DeleteChatroomAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="chat-user",
            password="test-password",
            name="채팅 사용자",
            department="인사팀",
        )
        self.chatroom = Chatroom.objects.create(
            chatroom_id="c620772d-0b7c-4480-a040-91b8d4ae9858",
            user=self.user,
            chatroom_name="삭제할 대화",
        )
        self.url = f"/chat/api/rooms/{self.chatroom.chatroom_id}/delete"

    def test_delete_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.delete(self.url)

        self.assertEqual(response.status_code, 403)
        self.chatroom.refresh_from_db()
        self.assertFalse(self.chatroom.is_deleted)

    def test_delete_soft_deletes_owned_chatroom_with_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get("/chat/")
        csrf_token = client.cookies["csrftoken"].value

        response = client.delete(self.url, HTTP_X_CSRFTOKEN=csrf_token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "삭제되었습니다.")
        self.chatroom.refresh_from_db()
        self.assertTrue(self.chatroom.is_deleted)
        self.assertIsNotNone(self.chatroom.deleted_at)

    def test_delete_returns_not_found_for_another_users_chatroom(self):
        other_user = User.objects.create_user(
            username="other-user",
            password="test-password",
            name="다른 사용자",
            department="총무팀",
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(other_user)
        client.get("/chat/")
        csrf_token = client.cookies["csrftoken"].value

        response = client.delete(self.url, HTTP_X_CSRFTOKEN=csrf_token)

        self.assertEqual(response.status_code, 404)
        self.chatroom.refresh_from_db()
        self.assertFalse(self.chatroom.is_deleted)

    def test_deleted_chatroom_is_omitted_from_room_list(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get("/chat/")
        csrf_token = client.cookies["csrftoken"].value

        client.delete(self.url, HTTP_X_CSRFTOKEN=csrf_token)
        response = client.get("/chat/api/rooms")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])


class ChatSourceMetadataTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="source-user",
            password="test-password",
            name="출처 사용자",
            department="인사팀",
        )
        self.chatroom = Chatroom.objects.create(
            chatroom_id="6fe2bc62-b85e-4ea4-a1a2-841385043bef",
            user=self.user,
            chatroom_name="병가 문의",
        )

    def test_article_metadata_survives_message_reload(self):
        answer = Chat.objects.create(
            chatroom=self.chatroom,
            speaker="llm",
            message="병가는 연 누계 2개월 범위에서 허가할 수 있습니다.",
        )
        ChatSource.objects.create(
            chat=answer,
            doc_id=10,
            file_name="복무규정.pdf",
            document_title="복무규정",
            article="제21조(병가)",
            page=5,
        )

        messages = get_messages(self.chatroom.chatroom_id, self.user.username)

        self.assertEqual(messages[0]["sources"][0]["document_title"], "복무규정")
        self.assertEqual(messages[0]["sources"][0]["article"], "제21조(병가)")
