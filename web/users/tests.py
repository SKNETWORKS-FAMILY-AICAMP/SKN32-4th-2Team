from urllib.parse import urlencode

from django.test import Client, TestCase

from users.models import User


class UpdateUserAPITests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin-user",
            password="test-password",
            name="관리자",
            department="인사팀",
            is_admin=True,
        )
        self.target = User.objects.create_user(
            username="target-user",
            password="old-password",
            name="수정 전",
            department="개발팀",
            is_admin=False,
            is_disabled=False,
        )
        self.url = f"/admin/users/api/{self.target.username}/update"

    def _authenticated_client(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        client.get("/admin/users/")
        return client, client.cookies["csrftoken"].value

    def test_patch_updates_urlencoded_form_data(self):
        client, csrf_token = self._authenticated_client()
        body = urlencode(
            {
                "name": "수정 후",
                "department": "총무팀",
                "passwd": "new-password",
                "is_admin": "true",
                "is_disabled": "true",
            }
        )

        response = client.patch(
            self.url,
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.name, "수정 후")
        self.assertEqual(self.target.department, "총무팀")
        self.assertTrue(self.target.is_admin)
        self.assertTrue(self.target.is_disabled)
        self.assertTrue(self.target.check_password("new-password"))

    def test_patch_preserves_boolean_values_when_they_are_omitted(self):
        self.target.is_admin = True
        self.target.is_disabled = True
        self.target.save()
        client, csrf_token = self._authenticated_client()

        response = client.patch(
            self.url,
            data=urlencode({"name": "이름만 수정"}),
            content_type="application/x-www-form-urlencoded",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.name, "이름만 수정")
        self.assertTrue(self.target.is_admin)
        self.assertTrue(self.target.is_disabled)

    def test_admin_cannot_remove_their_own_admin_privilege(self):
        client, csrf_token = self._authenticated_client()
        own_url = f"/admin/users/api/{self.admin.username}/update"

        response = client.patch(
            own_url,
            data=urlencode({"is_admin": "false"}),
            content_type="application/x-www-form-urlencoded",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_admin)
