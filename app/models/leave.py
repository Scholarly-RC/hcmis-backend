from datetime import date, datetime
from enum import Enum as PyEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.models.base import Base


class LeaveTypePolicy(Base):
    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("code", name="leave_types_code_key"),
        UniqueConstraint("name", name="leave_types_name_key"),
        CheckConstraint("max_credits >= 0", name="ck_leave_types_max_credits_non_negative"),
        CheckConstraint(
            "credit_mode IN ('incremental', 'fixed')",
            name="ck_leave_types_credit_mode",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4, index=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    max_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class LeaveType(str, PyEnum):
    PAID = "PA"
    UNPAID = "UN"
    WORK_RELATED_TRIP = "WR"


class LeaveRequestStatus(str, PyEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LeaveCredit(Base):
    __tablename__ = "leave_credits"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True, index=True
    )
    credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="leave_credit")

    @property
    def remaining_credits(self) -> int:
        return self.credits - self.used_credits


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    leave_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    leave_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    approval_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_approver_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    first_approver_status: Mapped[str] = mapped_column(
        String(20), default=LeaveRequestStatus.PENDING.value, nullable=False, index=True
    )
    first_approver_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    second_approver_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    second_approver_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    second_approver_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    escalated_to_backup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    escalated_to_backup_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=LeaveRequestStatus.PENDING.value, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="leave_requests", foreign_keys=[user_id])
    first_approver = relationship("User", foreign_keys=[first_approver_id])
    second_approver = relationship("User", foreign_keys=[second_approver_id])
    escalated_to_backup_by = relationship("User", foreign_keys=[escalated_to_backup_by_id])
    approver_pool = relationship(
        "LeaveRequestApprover",
        back_populates="leave_request",
        cascade="all, delete-orphan",
    )

    @property
    def is_ready_for_second_approver(self) -> bool:
        return (
            self.second_approver_id is not None
            and self.first_approver_status == LeaveRequestStatus.APPROVED.value
            and self.second_approver_status == LeaveRequestStatus.PENDING.value
        )


class LeaveRequestApprover(Base):
    __tablename__ = "leave_request_approvers"
    __table_args__ = (
        UniqueConstraint(
            "leave_request_id",
            "approver_id",
            name="uq_leave_request_approvers_leave_request_id_approver_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    leave_request_id: Mapped[int] = mapped_column(
        ForeignKey("leave_requests.id"), nullable=False, index=True
    )
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=LeaveRequestStatus.PENDING.value, nullable=False, index=True
    )
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    leave_request = relationship("LeaveRequest", back_populates="approver_pool")
    approver = relationship("User", foreign_keys=[approver_id])
