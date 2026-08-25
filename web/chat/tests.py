from django.test import Client, TestCase

from chat.models import Chatroom
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
