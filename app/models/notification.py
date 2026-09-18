from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    sender_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    recipient = relationship(
        "User",
        foreign_keys=[recipient_id],
        back_populates="notifications_received",
    )
    sender = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="notifications_sent",
    )
