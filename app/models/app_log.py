from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.models.base import Base


class AppLog(Base):
    __tablename__ = "app_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="logs")
