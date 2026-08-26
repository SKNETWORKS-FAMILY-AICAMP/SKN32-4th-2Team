"""Import legacy user and chat data into Django's database.

The command deliberately has no destructive or implicit write mode.  It first
builds a complete import plan from the ``legacy`` alias and only writes to the
``default`` alias when ``--apply`` is supplied.

RAG starts as a new corpus: legacy ``document`` metadata is intentionally
neither read nor written. ``chat_source`` citation snapshots are imported so
historical chats can still show their recorded file name and page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, transaction

from chat.models import Chat, Chatroom, ChatSource
from documents.models import Document
from legacy_import.models import (
    LegacyChat,
    LegacyChatSource,
    LegacyChatroom,
    LegacyUser,
    LegacyUserLoginHistory,
)
from users.models import User, UserLoginHistory


LEGACY_DB_ALIAS = "legacy"
IMPORT_BATCH_SIZE = 500


@dataclass(frozen=True)
class ImportSpec:
    """Describes one source-to-target table import."""

    label: str
    source_model: type[Any]
    target_model: type[Any]
    source_order_by: tuple[str, ...]
    build_target: Callable[[Any], Any]
    timestamp_fields: tuple[str, ...]
    parent_label: str | None = None
    parent_key_field: str | None = None


@dataclass
class ImportPlan:
    """Rows read from one legacy table and their safe target action."""

    spec: ImportSpec
    source_count: int
    source_rows: list[Any]
    source_pks: set[Any]
    existing_pks: set[Any]
    existing_count: int
    pending_rows: list[Any]

    @property
    def create_count(self) -> int:
        return len(self.pending_rows)


def _build_user(source: LegacyUser) -> User:
    # Do not use UserManager.create_user()/set_password(): passwd is already a
    # bcrypt hash in the legacy schema and hashing it again would break login.
    return User(
        username=source.user_id,
        password=source.passwd,
        last_login=None,
        is_superuser=False,
        name=source.name,
        department=source.department,
        is_admin=source.is_admin,
        is_disabled=source.is_disabled,
        is_deleted=source.is_deleted,
        created_at=source.created_at,
        updated_at=source.updated_at,
        deleted_at=source.deleted_at,
    )


def _build_login_history(source: LegacyUserLoginHistory) -> UserLoginHistory:
    return UserLoginHistory(
        history_id=source.history_id,
        user_id=source.user_id,
        created_at=source.created_at,
    )


def _build_chatroom(source: LegacyChatroom) -> Chatroom:
    return Chatroom(
        chatroom_id=source.chatroom_id,
        user_id=source.user_id,
        chatroom_name=source.chatroom_name,
        created_at=source.created_at,
        is_deleted=source.is_deleted,
        deleted_at=source.deleted_at,
    )


def _build_chat(source: LegacyChat) -> Chat:
    return Chat(
        chat_id=source.chat_id,
        chatroom_id=source.chatroom_id,
        speaker=source.speaker,
        message=source.message,
        topic=source.topic,
        created_at=source.created_at,
    )


def _build_chat_source(source: LegacyChatSource) -> ChatSource:
    """Preserve historical source snapshots without importing RAG documents."""

    return ChatSource(
        source_id=source.source_id,
        chat_id=source.chat_id,
        doc_id=source.doc_id,
        file_name=source.file_name,
        page=source.page,
        created_at=source.created_at,
    )


# FK parents precede children. RAG-managed ``document`` is deliberately absent
# so the target RAG corpus starts fresh, while chat citation snapshots remain.
IMPORT_SPECS = (
    ImportSpec(
        label="user",
        source_model=LegacyUser,
        target_model=User,
        source_order_by=("user_id",),
        build_target=_build_user,
        timestamp_fields=("created_at", "updated_at", "deleted_at"),
    ),
    ImportSpec(
        label="user_login_history",
        source_model=LegacyUserLoginHistory,
        target_model=UserLoginHistory,
        source_order_by=("history_id",),
        build_target=_build_login_history,
        timestamp_fields=("created_at",),
        parent_label="user",
        parent_key_field="user_id",
    ),
    ImportSpec(
        label="chatroom",
        source_model=LegacyChatroom,
        target_model=Chatroom,
        source_order_by=("chatroom_id",),
        build_target=_build_chatroom,
        timestamp_fields=("created_at", "deleted_at"),
        parent_label="user",
        parent_key_field="user_id",
    ),
    ImportSpec(
        label="chat",
        source_model=LegacyChat,
        target_model=Chat,
        source_order_by=("chat_id",),
        build_target=_build_chat,
        timestamp_fields=("created_at",),
        parent_label="chatroom",
        parent_key_field="chatroom_id",
    ),
    ImportSpec(
        label="chat_source",
        source_model=LegacyChatSource,
        target_model=ChatSource,
        source_order_by=("source_id",),
        build_target=_build_chat_source,
        timestamp_fields=("created_at",),
        parent_label="chat",
        parent_key_field="chat_id",
    ),
)


# This table is not migrated. Its target must nevertheless be empty so a
# legacy user/chat import cannot be combined with a pre-existing RAG corpus.
FRESH_RAG_TARGET_MODELS = (
    ("document", Document),
)


class Command(BaseCommand):
    help = (
        "Preview or import legacy user/chat data from alias 'legacy' into "
        "the Django-managed default database. RAG documents are excluded; "
        "chat citation snapshots are preserved. Use --apply to write."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the planned rows to the default database. Without this flag, no rows are written.",
        )
        parser.add_argument(
            "--allow-nonempty-target",
            action="store_true",
            help=(
                "Allow a resume into a non-empty target. Existing primary keys "
                "are skipped and never overwritten."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_changes = options["apply"]
        self._validate_database_aliases()
        if apply_changes:
            self._validate_fresh_rag_target()
            if not options["allow_nonempty_target"]:
                self._validate_target_is_empty()

        plans = [self._build_plan(spec) for spec in IMPORT_SPECS]
        self._preflight_foreign_keys(plans)

        if apply_changes:
            mode_message = "Legacy import mode: APPLY (writing to 'default')."
            if options["allow_nonempty_target"]:
                mode_message += " Non-empty target override is enabled."
            self.stdout.write(mode_message)
            with transaction.atomic(using=DEFAULT_DB_ALIAS):
                for plan in plans:
                    self._write_plan(plan)
                    self._write_count(plan, action="created")
            self.stdout.write(self.style.SUCCESS("Legacy import completed successfully."))
            return

        self.stdout.write(
            self.style.WARNING(
                "Legacy import mode: DRY RUN. No rows were written to 'default'."
            )
        )
        for plan in plans:
            self._write_count(
                plan,
                action="would create",
                include_latest_source_timestamp=True,
            )
        self.stdout.write("Run `manage.py import_legacy_data --apply` to perform this import.")

    def _validate_database_aliases(self) -> None:
        """Reject an absent or unsafe source alias before any source reads."""

        databases = settings.DATABASES
        if LEGACY_DB_ALIAS not in databases:
            raise CommandError(
                "The 'legacy' database alias is not configured. "
                "Configure it as the read-only legacy source before importing."
            )

        if DEFAULT_DB_ALIAS not in databases:
            raise CommandError("The 'default' database alias is not configured.")

        legacy_config = settings.DATABASES[LEGACY_DB_ALIAS]
        default_config = settings.DATABASES[DEFAULT_DB_ALIAS]
        if self._database_identity(legacy_config) == self._database_identity(default_config):
            raise CommandError(
                "The 'legacy' and 'default' aliases point to the same database. "
                "Use a separate target database before importing."
            )

    @staticmethod
    def _database_identity(config: dict[str, Any]) -> tuple[str, str, str, str]:
        """Return the parts that identify the physical database target."""

        return tuple(
            str(config.get(key, "")).strip().lower()
            for key in ("ENGINE", "NAME", "HOST", "PORT")
        )

    def _build_plan(self, spec: ImportSpec) -> ImportPlan:
        source_manager = spec.source_model._default_manager
        source_rows = list(
            source_manager.using(LEGACY_DB_ALIAS).order_by(*spec.source_order_by)
        )
        target_rows = [spec.build_target(source) for source in source_rows]
        target_pks = [row.pk for row in target_rows]

        if len(target_pks) != len(set(target_pks)):
            raise CommandError(
                f"Legacy table '{spec.label}' contains duplicate primary keys; import stopped."
            )

        existing_pks: set[Any] = set()
        if target_pks:
            existing_pks = set(
                spec.target_model._default_manager.using(DEFAULT_DB_ALIAS)
                .filter(pk__in=target_pks)
                .values_list("pk", flat=True)
            )

        pending_rows = [row for row in target_rows if row.pk not in existing_pks]
        return ImportPlan(
            spec=spec,
            source_count=len(source_rows),
            source_rows=target_rows,
            source_pks=set(target_pks),
            existing_pks=existing_pks,
            existing_count=len(existing_pks),
            pending_rows=pending_rows,
        )

    def _validate_target_is_empty(self) -> None:
        """Prevent accidental mixing of a legacy import with live user/chat data."""

        occupied_tables = []
        for spec in IMPORT_SPECS:
            count = spec.target_model._default_manager.using(DEFAULT_DB_ALIAS).count()
            if count:
                occupied_tables.append(f"{spec.label}={count}")

        if occupied_tables:
            raise CommandError(
                "Refusing to import into a non-empty target database "
                f"({', '.join(occupied_tables)}). Start with empty target tables, "
                "or use --allow-nonempty-target only to resume a reviewed import."
            )

    def _validate_fresh_rag_target(self) -> None:
        """Require a new RAG corpus even when a user/chat resume is allowed."""

        occupied_tables = []
        for label, target_model in FRESH_RAG_TARGET_MODELS:
            count = target_model._default_manager.using(DEFAULT_DB_ALIAS).count()
            if count:
                occupied_tables.append(f"{label}={count}")

        if occupied_tables:
            raise CommandError(
                "Refusing to import while the target RAG tables are non-empty "
                f"({', '.join(occupied_tables)}). Use a fresh target RAG corpus "
                "before importing legacy user/chat data."
            )

    def _preflight_foreign_keys(self, plans: list[ImportPlan]) -> None:
        """Fail before writes when a legacy child points at a missing parent."""

        plans_by_label = {plan.spec.label: plan for plan in plans}
        for plan in plans:
            parent_label = plan.spec.parent_label
            parent_key_field = plan.spec.parent_key_field
            if parent_label is None or parent_key_field is None:
                continue

            parent_plan = plans_by_label[parent_label]
            missing_parent_keys = {
                getattr(row, parent_key_field)
                for row in plan.source_rows
                if getattr(row, parent_key_field) not in parent_plan.source_pks
            }
            if missing_parent_keys:
                examples = ", ".join(
                    str(value) for value in sorted(missing_parent_keys, key=str)[:5]
                )
                raise CommandError(
                    "Legacy import preflight failed: "
                    f"'{plan.spec.label}' contains rows with missing "
                    f"{parent_label} parent keys ({examples})."
                )

    def _write_plan(self, plan: ImportPlan) -> None:
        if not plan.pending_rows:
            return

        target_manager = plan.spec.target_model._default_manager.using(
            DEFAULT_DB_ALIAS
        )

        # auto_now/auto_now_add fields are populated during bulk_create. Keep a
        # copy so a subsequent bulk_update restores the original legacy times.
        timestamp_values = [
            {
                field_name: getattr(row, field_name)
                for field_name in plan.spec.timestamp_fields
            }
            for row in plan.pending_rows
        ]

        target_manager.bulk_create(plan.pending_rows, batch_size=IMPORT_BATCH_SIZE)

        if plan.spec.timestamp_fields:
            for row, values in zip(plan.pending_rows, timestamp_values, strict=True):
                for field_name, value in values.items():
                    setattr(row, field_name, value)
            target_manager.bulk_update(
                plan.pending_rows,
                fields=plan.spec.timestamp_fields,
                batch_size=IMPORT_BATCH_SIZE,
            )

    def _write_count(
        self,
        plan: ImportPlan,
        *,
        action: str,
        include_latest_source_timestamp: bool = False,
    ) -> None:
        message = (
            f"  {plan.spec.label}: source={plan.source_count}, "
            f"{action}={plan.create_count}, already_exists={plan.existing_count}"
        )
        if include_latest_source_timestamp:
            latest_source_timestamp = self._latest_source_timestamp(plan)
            latest_display = (
                latest_source_timestamp.isoformat()
                if latest_source_timestamp is not None
                else "-"
            )
            message += f", latest_source_at={latest_display}"
        self.stdout.write(message)

    @staticmethod
    def _latest_source_timestamp(plan: ImportPlan) -> Any | None:
        timestamps = [
            getattr(row, field_name)
            for row in plan.source_rows
            for field_name in plan.spec.timestamp_fields
            if getattr(row, field_name) is not None
        ]
        return max(timestamps, default=None)
