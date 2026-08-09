"""Add standalone Account registration challenge contexts.

Revision ID: add_standalone_account_auth_v1
Revises: add_assessment_management_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_standalone_account_auth_v1"
down_revision: Union[str, None] = "add_assessment_management_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PHONE_PURPOSES_OLD = (
    "purpose IN ('invitation_registration', 'login', 'password_reset', "
    "'phone_change')"
)
_PHONE_PURPOSES_NEW = (
    "purpose IN ('invitation_registration', 'account_registration', 'login', "
    "'password_reset', 'phone_change')"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_phone_verification_challenges_purpose",
        "phone_verification_challenges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_purpose",
        "phone_verification_challenges",
        _PHONE_PURPOSES_NEW,
    )

    op.add_column(
        "device_registration_challenges",
        sa.Column(
            "registration_context",
            sa.String(length=40),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE device_registration_challenges "
        "SET registration_context = 'invitation_registration_v1' "
        "WHERE registration_context IS NULL"
    )
    op.alter_column(
        "device_registration_challenges",
        "registration_context",
        nullable=False,
    )
    op.alter_column(
        "device_registration_challenges",
        "invitation_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.alter_column(
        "device_registration_challenges",
        "employee_profile_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_device_registration_challenges_context",
        "device_registration_challenges",
        "registration_context IN ('invitation_registration_v1', "
        "'account_registration_v1')",
    )
    op.create_check_constraint(
        "ck_device_registration_challenges_context_fields",
        "device_registration_challenges",
        "((registration_context = 'invitation_registration_v1' "
        "AND invitation_id IS NOT NULL AND employee_profile_id IS NOT NULL) OR "
        "(registration_context = 'account_registration_v1' "
        "AND invitation_id IS NULL AND employee_profile_id IS NULL))",
    )
    op.create_index(
        "uq_device_registration_challenges_pending_account_device",
        "device_registration_challenges",
        ["phone_verification_challenge_id", "app_instance_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'pending' AND "
            "registration_context = 'account_registration_v1'"
        ),
    )


def downgrade() -> None:
    # Standalone rows cannot satisfy the historical non-null invitation shape.
    # Downgrade is deliberately reversible only when no such rows remain.
    connection = op.get_bind()
    remaining = connection.execute(
        sa.text(
            "SELECT count(*) FROM device_registration_challenges "
            "WHERE registration_context = 'account_registration_v1'"
        )
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            "cannot downgrade while standalone registration challenges exist"
        )
    op.drop_index(
        "uq_device_registration_challenges_pending_account_device",
        table_name="device_registration_challenges",
    )
    op.drop_constraint(
        "ck_device_registration_challenges_context_fields",
        "device_registration_challenges",
        type_="check",
    )
    op.drop_constraint(
        "ck_device_registration_challenges_context",
        "device_registration_challenges",
        type_="check",
    )
    op.alter_column(
        "device_registration_challenges",
        "employee_profile_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.alter_column(
        "device_registration_challenges",
        "invitation_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.drop_column("device_registration_challenges", "registration_context")
    op.drop_constraint(
        "ck_phone_verification_challenges_purpose",
        "phone_verification_challenges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_purpose",
        "phone_verification_challenges",
        _PHONE_PURPOSES_OLD,
    )
