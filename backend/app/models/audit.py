"""Append-only, publicly readable demonstration event log.

No foreign key to groups: a deleted room's log remains available.
"""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    group_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_audit_events_group_id_id", "group_id", "id"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )
