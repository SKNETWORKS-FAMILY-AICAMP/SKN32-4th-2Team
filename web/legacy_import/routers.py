"""Database-routing rules for the read-only legacy source."""


class LegacyImportRouter:
    """Sends legacy model reads to ``legacy`` and prevents its migrations."""

    legacy_app_label = "legacy_import"
    legacy_database_alias = "legacy"

    def db_for_read(self, model, **hints):
        """Route only legacy-import model reads to the legacy connection."""
        if model._meta.app_label == self.legacy_app_label:
            return self.legacy_database_alias
        return None

    def db_for_write(self, model, **hints):
        """Keep accidental legacy-model writes away from the target database.

        The model/queryset guards reject normal writes before this routing rule
        matters. Returning ``legacy`` is a second safeguard for low-level code:
        the source account is documented and provisioned as SELECT-only, rather
        than allowing a bypass to fall through to ``default``.
        """
        if model._meta.app_label == self.legacy_app_label:
            return self.legacy_database_alias
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """Permit relations within the legacy model set only."""
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        if labels == {self.legacy_app_label}:
            return True
        if self.legacy_app_label in labels:
            return False
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Never migrate the source database or legacy-import models."""
        if db == self.legacy_database_alias:
            return False
        if app_label == self.legacy_app_label:
            return False
        return None
