"""Application configuration for legacy source access."""

from django.apps import AppConfig


class LegacyImportConfig(AppConfig):
    """Registers the read-only legacy schema models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "legacy_import"
    verbose_name = "Legacy data import"
