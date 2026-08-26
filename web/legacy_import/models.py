"""Unmanaged, read-only mappings for the pre-Django MySQL schema."""

from django.db import models


class ReadOnlyLegacyModelError(RuntimeError):
    """Raised when code tries to change the legacy import source."""


class ReadOnlyLegacyQuerySet(models.QuerySet):
    """Reject bulk mutation APIs that bypass model instance methods."""

    @staticmethod
    def _raise_read_only():
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")

    def update(self, **kwargs):
        self._raise_read_only()

    def delete(self):
        self._raise_read_only()

    def _raw_delete(self, using):
        self._raise_read_only()

    def bulk_create(self, objs, **kwargs):
        self._raise_read_only()

    def bulk_update(self, objs, fields, **kwargs):
        self._raise_read_only()

    def get_or_create(self, defaults=None, **kwargs):
        self._raise_read_only()

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        self._raise_read_only()


class ReadOnlyLegacyManager(models.Manager.from_queryset(ReadOnlyLegacyQuerySet)):
    """Provides the read-only queryset through each legacy model manager."""

    def create(self, **kwargs):
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")

    def bulk_create(self, objs, **kwargs):
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")

    def get_or_create(self, defaults=None, **kwargs):
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")


class ReadOnlyLegacyModel(models.Model):
    """Base model that guarantees that legacy records cannot be changed."""

    objects = ReadOnlyLegacyManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Reject writes to the migration source."""
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")

    def delete(self, *args, **kwargs):
        """Reject deletion from the migration source."""
        raise ReadOnlyLegacyModelError("Legacy import models are read-only.")


class LegacyUser(ReadOnlyLegacyModel):
    """Unmanaged mapping of the legacy ``user`` table."""

    user_id = models.CharField(max_length=20, primary_key=True)
    passwd = models.CharField(max_length=255)
    name = models.CharField(max_length=50)
    department = models.CharField(max_length=100)
    is_admin = models.BooleanField(default=False)
    is_disabled = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "legacy_import"
        db_table = "user"
        managed = False


class LegacyUserLoginHistory(ReadOnlyLegacyModel):
    """Unmanaged mapping of the legacy ``user_login_history`` table."""

    history_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        LegacyUser,
        db_column="user_id",
        on_delete=models.PROTECT,
        related_name="+",
        to_field="user_id",
    )
    created_at = models.DateTimeField()

    class Meta:
        app_label = "legacy_import"
        db_table = "user_login_history"
        managed = False


class LegacyChatroom(ReadOnlyLegacyModel):
    """Unmanaged mapping of the legacy ``chatroom`` table."""

    chatroom_id = models.CharField(max_length=36, primary_key=True)
    user = models.ForeignKey(
        LegacyUser,
        db_column="user_id",
        on_delete=models.PROTECT,
        related_name="+",
        to_field="user_id",
    )
    chatroom_name = models.CharField(max_length=100)
    created_at = models.DateTimeField()
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "legacy_import"
        db_table = "chatroom"
        managed = False


class LegacyChat(ReadOnlyLegacyModel):
    """Unmanaged mapping of the legacy ``chat`` table."""

    SPEAKER_CHOICES = [("user", "User"), ("llm", "LLM")]

    chat_id = models.AutoField(primary_key=True)
    chatroom = models.ForeignKey(
        LegacyChatroom,
        db_column="chatroom_id",
        on_delete=models.PROTECT,
        related_name="+",
        to_field="chatroom_id",
    )
    speaker = models.CharField(max_length=4, choices=SPEAKER_CHOICES)
    message = models.TextField()
    topic = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        app_label = "legacy_import"
        db_table = "chat"
        managed = False


class LegacyChatSource(ReadOnlyLegacyModel):
    """Unmanaged mapping of historical chat citation snapshots."""

    source_id = models.AutoField(primary_key=True)
    chat = models.ForeignKey(
        LegacyChat,
        db_column="chat_id",
        on_delete=models.CASCADE,
        related_name="+",
        to_field="chat_id",
    )
    doc_id = models.IntegerField(null=True, blank=True)
    file_name = models.CharField(max_length=255)
    page = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        app_label = "legacy_import"
        db_table = "chat_source"
        managed = False
