"""Tests for the safe one-off legacy import management command."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from chat.models import Chat, Chatroom, ChatSource
from documents.models import Document
from legacy_import.management.commands import import_legacy_data
from users.models import User, UserLoginHistory


class FakeLegacyQuerySet:
    """Minimal read-only queryset stand-in that records the selected alias."""

    def __init__(self, rows):
        self.rows = rows
        self.alias = None
        self.ordering = None

    def using(self, alias):
        self.alias = alias
        return self

    def order_by(self, *fields):
        self.ordering = fields
        return self

    def __iter__(self):
        return iter(self.rows)


class LegacyImportCommandTests(TestCase):
    """Exercise import planning without connecting to an external MySQL DB."""

    def setUp(self):
        self.source_time = timezone.now() - timedelta(days=2)
        self.updated_time = self.source_time + timedelta(hours=3)
        self.managers = {}

    @contextmanager
    def legacy_alias(self, config=None):
        """Temporarily add a distinct source config without opening it."""

        sentinel = object()
        previous = settings.DATABASES.get("legacy", sentinel)
        settings.DATABASES["legacy"] = config or {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "legacy-import-source.sqlite3",
            "HOST": "",
            "PORT": "",
        }
        try:
            yield
        finally:
            if previous is sentinel:
                settings.DATABASES.pop("legacy", None)
            else:
                settings.DATABASES["legacy"] = previous

    def import_specs_for(self, rows_by_label):
        specs = []
        for spec in import_legacy_data.IMPORT_SPECS:
            manager = FakeLegacyQuerySet(rows_by_label.get(spec.label, []))
            source_model = type(
                f"Fake{spec.label.title().replace('_', '')}",
                (),
                {"_default_manager": manager},
            )
            self.managers[spec.label] = manager
            specs.append(replace(spec, source_model=source_model))
        return tuple(specs)

    def sample_rows(self):
        return {
            "user": [
                SimpleNamespace(
                    user_id="legacy-user",
                    passwd="$2b$12$already-hashed-password-value",
                    name="레거시 사용자",
                    department="AI팀",
                    is_admin=True,
                    is_disabled=False,
                    is_deleted=False,
                    created_at=self.source_time,
                    updated_at=self.updated_time,
                    deleted_at=None,
                )
            ],
            "user_login_history": [
                SimpleNamespace(
                    history_id=41,
                    user_id="legacy-user",
                    created_at=self.source_time,
                )
            ],
            "chatroom": [
                SimpleNamespace(
                    chatroom_id="11111111-1111-1111-1111-111111111111",
                    user_id="legacy-user",
                    chatroom_name="이전 대화",
                    created_at=self.source_time,
                    is_deleted=False,
                    deleted_at=None,
                )
            ],
            "chat": [
                SimpleNamespace(
                    chat_id=51,
                    chatroom_id="11111111-1111-1111-1111-111111111111",
                    speaker="user",
                    message="기존 메시지",
                    topic="이관",
                    created_at=self.source_time,
                )
            ],
            "chat_source": [
                SimpleNamespace(
                    source_id=61,
                    chat_id=51,
                    # The new RAG corpus will not contain this legacy doc_id;
                    # file_name/page remain the historical citation snapshot.
                    doc_id=71,
                    file_name="legacy.pdf",
                    page=3,
                    created_at=self.source_time,
                )
            ],
        }

    def test_import_specs_exclude_documents_but_preserve_citation_snapshots(self):
        self.assertEqual(
            tuple(spec.label for spec in import_legacy_data.IMPORT_SPECS),
            ("user", "user_login_history", "chatroom", "chat", "chat_source"),
        )

    def test_dry_run_reads_legacy_and_never_writes_default(self):
        specs = self.import_specs_for(self.sample_rows())
        output = StringIO()

        with self.legacy_alias(), patch.object(
            import_legacy_data, "IMPORT_SPECS", specs
        ):
            call_command("import_legacy_data", stdout=output)

        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(UserLoginHistory.objects.count(), 0)
        self.assertEqual(Chatroom.objects.count(), 0)
        self.assertEqual(Chat.objects.count(), 0)
        self.assertEqual(ChatSource.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
        self.assertTrue(
            all(manager.alias == "legacy" for manager in self.managers.values())
        )

        rendered = output.getvalue()
        self.assertIn("DRY RUN", rendered)
        self.assertIn("user: source=1, would create=1, already_exists=0", rendered)
        self.assertIn(
            f"latest_source_at={self.updated_time.isoformat()}", rendered
        )
        self.assertIn("--apply", rendered)

    def test_apply_preserves_user_chat_and_citation_snapshot_data(self):
        specs = self.import_specs_for(self.sample_rows())
        output = StringIO()

        with self.legacy_alias(), patch.object(
            import_legacy_data, "IMPORT_SPECS", specs
        ):
            call_command("import_legacy_data", "--apply", stdout=output)

        user = User.objects.get(username="legacy-user")
        self.assertEqual(user.password, "$2b$12$already-hashed-password-value")
        self.assertIsNone(user.last_login)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.created_at, self.source_time)
        self.assertEqual(user.updated_at, self.updated_time)

        self.assertEqual(UserLoginHistory.objects.get(pk=41).user_id, "legacy-user")
        self.assertEqual(
            Chatroom.objects.get(pk="11111111-1111-1111-1111-111111111111").user_id,
            "legacy-user",
        )
        self.assertEqual(
            Chat.objects.get(pk=51).chatroom_id,
            "11111111-1111-1111-1111-111111111111",
        )
        citation = ChatSource.objects.get(pk=61)
        self.assertEqual(citation.chat_id, 51)
        self.assertEqual(citation.doc_id, 71)
        self.assertEqual(citation.file_name, "legacy.pdf")
        self.assertEqual(citation.page, 3)
        self.assertEqual(citation.created_at, self.source_time)
        self.assertEqual(Document.objects.count(), 0)

        rendered = output.getvalue()
        self.assertIn("APPLY", rendered)
        self.assertIn("chat_source: source=1, created=1, already_exists=0", rendered)
        self.assertNotIn("document:", rendered)
        self.assertIn("completed successfully", rendered)

    def test_existing_primary_keys_are_reported_and_not_overwritten(self):
        existing = User.objects.create_user(
            username="legacy-user",
            password="current-password",
            name="현재 사용자",
            department="개발팀",
        )
        specs = self.import_specs_for({"user": self.sample_rows()["user"]})
        output = StringIO()

        with self.legacy_alias(), patch.object(
            import_legacy_data, "IMPORT_SPECS", specs
        ):
            call_command(
                "import_legacy_data",
                "--apply",
                "--allow-nonempty-target",
                stdout=output,
            )

        existing.refresh_from_db()
        self.assertEqual(existing.name, "현재 사용자")
        self.assertIn("user: source=1, created=0, already_exists=1", output.getvalue())

    def test_apply_refuses_a_nonempty_target_without_explicit_override(self):
        User.objects.create_user(
            username="current-user",
            password="current-password",
            name="현재 사용자",
            department="개발팀",
        )
        specs = self.import_specs_for(self.sample_rows())

        with self.legacy_alias(), patch.object(
            import_legacy_data, "IMPORT_SPECS", specs
        ):
            with self.assertRaisesMessage(CommandError, "non-empty target"):
                call_command("import_legacy_data", "--apply")

        self.assertEqual(User.objects.filter(username="legacy-user").count(), 0)
        self.assertTrue(all(manager.alias is None for manager in self.managers.values()))

    def test_apply_rejects_existing_rag_documents_even_with_nonempty_override(self):
        Document.objects.create(
            original_file_name="already-indexed.pdf",
            stored_file_name="doc_already-indexed.pdf",
            file_path="res/pdf/already-indexed.pdf",
        )
        specs = self.import_specs_for(self.sample_rows())

        with self.legacy_alias(), patch.object(
            import_legacy_data, "IMPORT_SPECS", specs
        ):
            with self.assertRaisesMessage(CommandError, "target RAG tables are non-empty"):
                call_command(
                    "import_legacy_data",
                    "--apply",
                    "--allow-nonempty-target",
                )

        self.assertEqual(User.objects.filter(username="legacy-user").count(), 0)
        self.assertTrue(all(manager.alias is None for manager in self.managers.values()))

    def test_preflight_rejects_orphaned_legacy_foreign_key_before_writes(self):
        orphan_room = SimpleNamespace(
            chatroom_id="22222222-2222-2222-2222-222222222222",
            user_id="missing-user",
            chatroom_name="고아 대화",
            created_at=self.source_time,
            is_deleted=False,
            deleted_at=None,
        )
        specs = self.import_specs_for({"chatroom": [orphan_room]})

        with self.legacy_alias(), patch.object(
            import_legacy_data, "IMPORT_SPECS", specs
        ):
            with self.assertRaisesMessage(CommandError, "missing user parent"):
                call_command("import_legacy_data", "--apply")

        self.assertEqual(Chatroom.objects.count(), 0)

    def test_missing_legacy_alias_is_rejected_before_reading(self):
        sentinel = object()
        previous = settings.DATABASES.pop("legacy", sentinel)
        try:
            with self.assertRaisesMessage(CommandError, "not configured"):
                call_command("import_legacy_data")
        finally:
            if previous is not sentinel:
                settings.DATABASES["legacy"] = previous

    def test_legacy_alias_cannot_point_to_default_database(self):
        default_config = dict(settings.DATABASES["default"])

        with self.legacy_alias(config=default_config):
            with self.assertRaisesMessage(CommandError, "same database"):
                call_command("import_legacy_data")
