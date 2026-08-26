"""Unit tests for the legacy adapter without a MySQL connection."""

from django.test import SimpleTestCase

from .models import (
    LegacyChat,
    LegacyChatSource,
    LegacyChatroom,
    LegacyUser,
    LegacyUserLoginHistory,
    ReadOnlyLegacyModelError,
)
from .routers import LegacyImportRouter


class LegacyModelMetadataTests(SimpleTestCase):
    """Validate source-table mappings and local read-only protections."""

    def test_models_are_unmanaged_with_expected_tables(self):
        expected_tables = {
            LegacyUser: "user",
            LegacyUserLoginHistory: "user_login_history",
            LegacyChatroom: "chatroom",
            LegacyChat: "chat",
            LegacyChatSource: "chat_source",
        }

        for model, table_name in expected_tables.items():
            self.assertFalse(model._meta.managed)
            self.assertEqual(model._meta.db_table, table_name)

    def test_user_uses_the_legacy_passwd_column(self):
        self.assertEqual(LegacyUser._meta.get_field("user_id").column, "user_id")
        self.assertEqual(LegacyUser._meta.get_field("passwd").column, "passwd")

    def test_instance_and_queryset_mutations_are_rejected(self):
        legacy_user = LegacyUser(user_id="legacy-user")

        with self.assertRaises(ReadOnlyLegacyModelError):
            legacy_user.save()
        with self.assertRaises(ReadOnlyLegacyModelError):
            legacy_user.delete()
        with self.assertRaises(ReadOnlyLegacyModelError):
            LegacyUser.objects.create(user_id="legacy-user")
        with self.assertRaises(ReadOnlyLegacyModelError):
            LegacyUser.objects.filter(user_id="legacy-user").update(name="updated")


class LegacyImportRouterTests(SimpleTestCase):
    """Validate router decisions without establishing a database connection."""

    def setUp(self):
        self.router = LegacyImportRouter()

    def test_reads_use_legacy_alias_only_for_legacy_models(self):
        self.assertEqual(self.router.db_for_read(LegacyUser), "legacy")
        self.assertIsNone(self.router.db_for_read(NonLegacyModel))

    def test_writes_stay_off_the_target_and_migrations_are_blocked(self):
        self.assertEqual(self.router.db_for_write(LegacyUser), "legacy")
        self.assertIsNone(self.router.db_for_write(NonLegacyModel))
        self.assertFalse(self.router.allow_migrate("legacy", "users"))
        self.assertFalse(self.router.allow_migrate("default", "legacy_import"))
        self.assertIsNone(self.router.allow_migrate("default", "users"))


class NonLegacyModel:
    """Small stand-in for a model outside of the legacy app."""

    class _meta:
        app_label = "users"
