"""Add reusable onboarding invitations and tenant-bound task workflows.

Revision ID: add_organization_workflows_v1
Revises: add_attempt_ui_metadata_v1
"""

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_organization_workflows_v1"
down_revision: Union[str, None] = "add_attempt_ui_metadata_v1"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "employee_profiles",
        sa.Column("birth_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "positions",
        sa.Column("default_scope_type", sa.String(length=30), nullable=True),
    )
    op.create_check_constraint(
        "ck_positions_default_scope_type",
        "positions",
        "default_scope_type IS NULL OR default_scope_type IN "
        "('self', 'working_venues', 'explicit_venues', 'company')",
    )
    op.drop_constraint(
        "ck_employee_profiles_status",
        "employee_profiles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_employee_profiles_status",
        "employee_profiles",
        "employment_status IN "
        "('invited', 'pending_activation', 'active', 'suspended', 'terminated')",
    )

    op.create_table(
        "group_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("access_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_by_account_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column(
            "max_registrations", sa.Integer(), server_default="50", nullable=False
        ),
        sa.Column(
            "registration_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by_account_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active','revoked','expired')",
            name="ck_group_invitations_status",
        ),
        sa.CheckConstraint(
            "octet_length(token_digest) = 32", name="ck_group_invitations_digest"
        ),
        sa.CheckConstraint(
            "max_registrations BETWEEN 1 AND 200",
            name="ck_group_invitations_capacity",
        ),
        sa.CheckConstraint(
            "registration_count BETWEEN 0 AND max_registrations",
            name="ck_group_invitations_count",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_group_invitations_expiry"
        ),
        sa.CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL "
            "AND revoked_by_account_id IS NOT NULL) OR "
            "(status <> 'revoked' AND revoked_at IS NULL "
            "AND revoked_by_account_id IS NULL)",
            name="ck_group_invitations_revoke_state",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_group_invitations_venue_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_id", "company_id"],
            ["positions.id", "positions.company_id"],
            name="fk_group_invitations_position_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_group_invitations_access_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_group_invitations_id_company"),
        sa.UniqueConstraint(
            "company_id", "request_id", name="uq_group_invitations_company_request"
        ),
    )
    op.create_index(
        "ix_group_invitations_company_status",
        "group_invitations",
        ["company_id", "status"],
    )
    op.create_index(
        "uq_group_invitations_active_digest",
        "group_invitations",
        ["token_digest"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "group_invitation_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "group_invitation_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="pending_activation",
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "activated_by_account_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending_activation','active','rejected')",
            name="ck_group_registrations_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND activated_at IS NOT NULL "
            "AND activated_by_account_id IS NOT NULL) OR "
            "(status <> 'active' AND activated_at IS NULL "
            "AND activated_by_account_id IS NULL)",
            name="ck_group_registrations_activation_state",
        ),
        sa.ForeignKeyConstraint(
            ["group_invitation_id", "company_id"],
            ["group_invitations.id", "group_invitations.company_id"],
            name="fk_group_registrations_invitation_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_group_registrations_profile_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_invitation_id",
            "request_id",
            name="uq_group_registrations_request",
        ),
    )
    op.create_index(
        "ix_group_registrations_company_status",
        "group_invitation_registrations",
        ["company_id", "status"],
    )
    op.create_index(
        "uq_group_registrations_company_account",
        "group_invitation_registrations",
        ["company_id", "account_id"],
        unique=True,
        postgresql_where=sa.text("account_id IS NOT NULL AND status <> 'rejected'"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assessment_attempt_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("author_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft','assigned','completed','cancelled')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_tasks_version"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_tasks_venue_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["author_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_tasks_id_company"),
        sa.UniqueConstraint(
            "author_account_id", "request_id", name="uq_tasks_author_request"
        ),
    )
    op.create_index(
        "ix_tasks_company_status", "tasks", ["company_id", "status"]
    )
    op.create_index("ix_tasks_attempt", "tasks", ["assessment_attempt_id"])

    op.create_table(
        "task_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=30), server_default="assigned", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewed_by_account_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN "
            "('assigned','submitted_for_review','changes_requested','accepted')",
            name="ck_task_assignments_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_task_assignments_version"),
        sa.ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["tasks.id", "tasks.company_id"],
            name="fk_task_assignments_task_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_task_assignments_profile_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "task_id", "company_id", name="uq_task_assignments_id_task_company"
        ),
        sa.UniqueConstraint(
            "task_id", "employee_profile_id", name="uq_task_assignments_task_employee"
        ),
    )
    op.create_index(
        "ix_task_assignments_employee_status",
        "task_assignments",
        ["employee_profile_id", "status"],
    )

    op.create_table(
        "task_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "uploaded_by_account_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=40), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256_digest", sa.LargeBinary(), nullable=False),
        sa.Column(
            "media_status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "media_status IN ('pending','ready','deleted')",
            name="ck_task_photos_status",
        ),
        sa.CheckConstraint(
            "mime_type IN ('image/jpeg','image/png')", name="ck_task_photos_mime"
        ),
        sa.CheckConstraint(
            "byte_size BETWEEN 1 AND 10485760", name="ck_task_photos_size"
        ),
        sa.CheckConstraint(
            "octet_length(sha256_digest) = 32", name="ck_task_photos_digest"
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["tasks.id", "tasks.company_id"],
            name="fk_task_photos_task_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_assignment_id", "task_id", "company_id"],
            ["task_assignments.id", "task_assignments.task_id", "task_assignments.company_id"],
            name="fk_task_photos_assignment_task_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_task_photos_object_key"),
    )
    op.create_index(
        "ix_task_photos_task_status",
        "task_photos",
        ["task_id", "media_status"],
    )

    op.create_table(
        "task_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column(
            "safe_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["tasks.id", "tasks.company_id"],
            name="fk_task_events_task_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_events_task_created",
        "task_events",
        ["task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_events_task_created", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_task_photos_task_status", table_name="task_photos")
    op.drop_table("task_photos")
    op.drop_index(
        "ix_task_assignments_employee_status", table_name="task_assignments"
    )
    op.drop_table("task_assignments")
    op.drop_index("ix_tasks_attempt", table_name="tasks")
    op.drop_index("ix_tasks_company_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(
        "uq_group_registrations_company_account",
        table_name="group_invitation_registrations",
    )
    op.drop_index(
        "ix_group_registrations_company_status",
        table_name="group_invitation_registrations",
    )
    op.drop_table("group_invitation_registrations")
    op.drop_index("uq_group_invitations_active_digest", table_name="group_invitations")
    op.drop_index("ix_group_invitations_company_status", table_name="group_invitations")
    op.drop_table("group_invitations")

    op.drop_constraint(
        "ck_employee_profiles_status",
        "employee_profiles",
        type_="check",
    )
    # ``pending_activation`` is the new workflow's non-active equivalent of the
    # legacy ``invited`` state. Collapse it before restoring the legacy check
    # so a downgrade remains possible after legitimate group-invite joins.
    op.execute(
        sa.text(
            "UPDATE employee_profiles "
            "SET employment_status = 'invited' "
            "WHERE employment_status = 'pending_activation'"
        )
    )
    op.create_check_constraint(
        "ck_employee_profiles_status",
        "employee_profiles",
        "employment_status IN ('invited', 'active', 'suspended', 'terminated')",
    )
    op.drop_column("employee_profiles", "birth_date")
    op.drop_constraint(
        "ck_positions_default_scope_type", "positions", type_="check"
    )
    op.drop_column("positions", "default_scope_type")
