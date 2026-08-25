from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class Document(models.Model):
    """Metadata for a file managed by the RAG document API."""

    doc_id = models.AutoField(primary_key=True)
    original_file_name = models.CharField(max_length=255)
    stored_file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    created_at = models.DateTimeField(
        default=timezone.now,
        db_default=Now(),
        editable=False,
    )
    is_loaded = models.BooleanField(default=False, db_default=False)
    loaded_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "document"
        indexes = [
            models.Index(
                fields=["is_deleted", "created_at"],
                name="document_visible_idx",
            )
        ]
