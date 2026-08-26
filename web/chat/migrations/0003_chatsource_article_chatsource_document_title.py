# Generated manually to preserve verified RAG source metadata in chat history.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsource",
            name="article",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="chatsource",
            name="document_title",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
