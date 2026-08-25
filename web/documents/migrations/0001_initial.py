# Generated manually for the RAG document metadata table.

from django.db import migrations, models
from django.db.models.functions import Now
from django.utils import timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Document",
            fields=[
                ("doc_id", models.AutoField(primary_key=True, serialize=False)),
                ("original_file_name", models.CharField(max_length=255)),
                ("stored_file_name", models.CharField(max_length=255)),
                ("file_path", models.CharField(max_length=500)),
                (
                    "created_at",
                    models.DateTimeField(
                        db_default=Now(),
                        default=timezone.now,
                        editable=False,
                    ),
                ),
                (
                    "is_loaded",
                    models.BooleanField(db_default=False, default=False),
                ),
                ("loaded_at", models.DateTimeField(blank=True, null=True)),
                (
                    "is_deleted",
                    models.BooleanField(db_default=False, default=False),
                ),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "document",
                "indexes": [
                    models.Index(
                        fields=["is_deleted", "created_at"],
                        name="document_visible_idx",
                    )
                ],
            },
        )
    ]
