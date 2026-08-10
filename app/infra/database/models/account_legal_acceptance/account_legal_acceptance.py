"""Append-only evidence for the legal set accepted at first Account creation."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base


class AccountLegalAcceptance(Base):
    __tablename__ = "account_legal_acceptances"
    __table_args__ = (
        CheckConstraint(
            "context = 'account_registration'",
            name="ck_account_legal_acceptances_context",
        ),
        CheckConstraint(
            "octet_length(terms_document_sha256) = 32",
            name="ck_account_legal_acceptances_terms_hash",
        ),
        CheckConstraint(
            "octet_length(privacy_document_sha256) = 32",
            name="ck_account_legal_acceptances_privacy_hash",
        ),
        UniqueConstraint(
            "account_id",
            "context",
            "document_set_version",
            name="uq_account_legal_acceptances_account_context_set",
        ),
        Index("ix_account_legal_acceptances_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    context: Mapped[str] = mapped_column(String(40), nullable=False)
    document_set_version: Mapped[str] = mapped_column(String(100), nullable=False)
    terms_version: Mapped[str] = mapped_column(String(100), nullable=False)
    terms_document_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    privacy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    privacy_document_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
