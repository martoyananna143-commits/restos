"""Add immutable Account registration legal evidence.

Revision ID: add_account_legal_acceptance_v1
Revises: add_standalone_account_auth_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_account_legal_acceptance_v1"
down_revision: Union[str, None] = "add_standalone_account_auth_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column_type in (
        ("pd_consent_version", sa.String(length=100)),
        ("pd_consent_document_sha256", sa.LargeBinary()),
        ("pd_consent_accepted_at", sa.DateTime(timezone=True)),
        ("auth_sms_consent_version", sa.String(length=100)),
        ("auth_sms_consent_copy_sha256", sa.LargeBinary()),
        ("auth_sms_consent_accepted_at", sa.DateTime(timezone=True)),
        ("auth_sms_message_type", sa.String(length=40)),
    ):
        op.add_column(
            "phone_verification_challenges",
            sa.Column(name, column_type, nullable=True),
        )

    op.create_check_constraint(
        "ck_phone_verification_challenges_pd_consent_hash",
        "phone_verification_challenges",
        "pd_consent_document_sha256 IS NULL OR octet_length(pd_consent_document_sha256) = 32",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_sms_consent_hash",
        "phone_verification_challenges",
        "auth_sms_consent_copy_sha256 IS NULL OR octet_length(auth_sms_consent_copy_sha256) = 32",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_sms_message_type",
        "phone_verification_challenges",
        "auth_sms_message_type IS NULL OR auth_sms_message_type IN ('registration_otp', 'password_recovery_otp')",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_pd_consent_complete",
        "phone_verification_challenges",
        "((pd_consent_version IS NULL AND pd_consent_document_sha256 IS NULL AND pd_consent_accepted_at IS NULL) OR "
        "(pd_consent_version IS NOT NULL AND pd_consent_document_sha256 IS NOT NULL AND pd_consent_accepted_at IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_sms_consent_complete",
        "phone_verification_challenges",
        "((auth_sms_consent_version IS NULL AND auth_sms_consent_copy_sha256 IS NULL AND auth_sms_consent_accepted_at IS NULL AND auth_sms_message_type IS NULL) OR "
        "(auth_sms_consent_version IS NOT NULL AND auth_sms_consent_copy_sha256 IS NOT NULL AND auth_sms_consent_accepted_at IS NOT NULL AND auth_sms_message_type IS NOT NULL))",
    )

    op.create_table(
        "account_legal_acceptances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("context", sa.String(length=40), nullable=False),
        sa.Column("document_set_version", sa.String(length=100), nullable=False),
        sa.Column("terms_version", sa.String(length=100), nullable=False),
        sa.Column("terms_document_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("privacy_version", sa.String(length=100), nullable=False),
        sa.Column("privacy_document_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "context = 'account_registration'",
            name="ck_account_legal_acceptances_context",
        ),
        sa.CheckConstraint(
            "octet_length(terms_document_sha256) = 32",
            name="ck_account_legal_acceptances_terms_hash",
        ),
        sa.CheckConstraint(
            "octet_length(privacy_document_sha256) = 32",
            name="ck_account_legal_acceptances_privacy_hash",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_account_legal_acceptances_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_legal_acceptances"),
        sa.UniqueConstraint(
            "account_id",
            "context",
            "document_set_version",
            name="uq_account_legal_acceptances_account_context_set",
        ),
    )
    op.create_index(
        "ix_account_legal_acceptances_account_id",
        "account_legal_acceptances",
        ["account_id"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    evidence = connection.execute(
        sa.text("SELECT count(*) FROM account_legal_acceptances")
    ).scalar_one()
    consent = connection.execute(
        sa.text(
            "SELECT count(*) FROM phone_verification_challenges "
            "WHERE pd_consent_accepted_at IS NOT NULL "
            "OR auth_sms_consent_accepted_at IS NOT NULL"
        )
    ).scalar_one()
    if evidence or consent:
        raise RuntimeError("cannot downgrade while P0-LEGAL evidence exists")

    op.drop_index(
        "ix_account_legal_acceptances_account_id",
        table_name="account_legal_acceptances",
    )
    op.drop_table("account_legal_acceptances")
    for constraint in (
        "ck_phone_verification_challenges_sms_consent_complete",
        "ck_phone_verification_challenges_pd_consent_complete",
        "ck_phone_verification_challenges_sms_message_type",
        "ck_phone_verification_challenges_sms_consent_hash",
        "ck_phone_verification_challenges_pd_consent_hash",
    ):
        op.drop_constraint(
            constraint,
            "phone_verification_challenges",
            type_="check",
        )
    for column in (
        "auth_sms_message_type",
        "auth_sms_consent_accepted_at",
        "auth_sms_consent_copy_sha256",
        "auth_sms_consent_version",
        "pd_consent_accepted_at",
        "pd_consent_document_sha256",
        "pd_consent_version",
    ):
        op.drop_column("phone_verification_challenges", column)
