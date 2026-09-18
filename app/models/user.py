from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.models.base import Base
from app.models.app_log import AppLog  # noqa: F401
from app.models.chat import Message  # noqa: F401
from app.models.department import Department  # noqa: F401
from app.models.leave import LeaveCredit  # noqa: F401
from app.models.leave import LeaveRequest  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.special_requests import CertificateAttendanceRequest  # noqa: F401
from app.models.special_requests import OfficialBusinessRequest  # noqa: F401


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "level_1_approver_id IS NULL OR level_2_approver_id IS NULL OR level_1_approver_id <> level_2_approver_id",
            name="ck_users_approvers_distinct",
        ),
        CheckConstraint(
            "monthly_salary IS NULL OR monthly_salary >= 0",
            name="ck_users_monthly_salary_nonnegative",
        ),
        UniqueConstraint("email", name="users_email_key"),
        Index("ix_users_biometric_uid", "biometric_uid"),
        Index("ix_users_department_id", "department_id"),
        Index("ix_users_position_id", "position_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(100), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    temporary_password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    highest_education_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    highest_education_program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    civil_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    religion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    monthly_salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    employee_number: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    biometric_uid: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    employee_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    employment_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    level_1_approver_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    level_2_approver_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    phone_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_of_hiring: Mapped[date | None] = mapped_column(Date, nullable=True)
    resignation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    profile_picture_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    can_modify_shift: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    department = relationship("Department", back_populates="users")
    position = relationship("Position")
    level_1_approver = relationship("User", foreign_keys=[level_1_approver_id], remote_side=[id])
    level_2_approver = relationship("User", foreign_keys=[level_2_approver_id], remote_side=[id])
    notifications_received = relationship(
        "Notification",
        foreign_keys="Notification.recipient_id",
        back_populates="recipient",
    )
    notifications_sent = relationship(
        "Notification",
        foreign_keys="Notification.sender_id",
        back_populates="sender",
    )
    logs = relationship("AppLog", back_populates="user")
    leave_requests = relationship(
        "LeaveRequest",
        back_populates="user",
        foreign_keys="LeaveRequest.user_id",
    )
    leave_credit = relationship("LeaveCredit", back_populates="user", uselist=False)
    attendance_records = relationship("AttendanceRecord", back_populates="user")
    employee_shift_assignments = relationship("EmployeeShiftAssignment", back_populates="user")
    shift_templates = relationship(
        "ShiftTemplate",
        secondary="user_shifts",
        back_populates="users",
    )
    overtime_requests = relationship(
        "OvertimeRequest",
        foreign_keys="OvertimeRequest.user_id",
        back_populates="user",
    )
    overtime_approvals = relationship(
        "OvertimeRequest",
        foreign_keys="OvertimeRequest.approver_id",
        back_populates="approver",
    )
    official_business_requests = relationship(
        "OfficialBusinessRequest",
        foreign_keys="OfficialBusinessRequest.user_id",
        back_populates="user",
    )
    official_business_approvals = relationship(
        "OfficialBusinessRequest",
        foreign_keys="OfficialBusinessRequest.approver_id",
        back_populates="approver",
    )
    certificate_attendance_requests = relationship(
        "CertificateAttendanceRequest",
        foreign_keys="CertificateAttendanceRequest.user_id",
        back_populates="user",
    )
    certificate_attendance_approvals = relationship(
        "CertificateAttendanceRequest",
        foreign_keys="CertificateAttendanceRequest.approver_id",
        back_populates="approver",
    )
    shift_swap_requests = relationship(
        "ShiftSwapRequest",
        foreign_keys="ShiftSwapRequest.requested_by_id",
        back_populates="requested_by",
    )
    shift_swap_targets = relationship(
        "ShiftSwapRequest",
        foreign_keys="ShiftSwapRequest.requested_for_id",
        back_populates="requested_for",
    )
    shift_swap_approvals = relationship(
        "ShiftSwapRequest",
        foreign_keys="ShiftSwapRequest.approver_id",
        back_populates="approver",
    )
    payslips = relationship("Payslip", back_populates="user")
    thirteenth_month_payouts = relationship("ThirteenthMonthPayout", back_populates="user")
    position_assignments = relationship(
        "UserPositionAssignment",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserPositionAssignment.user_id",
        order_by="UserPositionAssignment.effective_from.desc()",
    )
    salary_assignments = relationship(
        "UserSalaryAssignment",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserSalaryAssignment.user_id",
        order_by="UserSalaryAssignment.effective_from.desc()",
    )
    employment_movements = relationship(
        "UserEmploymentMovement",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserEmploymentMovement.user_id",
        order_by="UserEmploymentMovement.changed_at.desc()",
    )
    messages_sent = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender",
    )
    messages_received = relationship(
        "Message",
        foreign_keys="Message.receiver_id",
        back_populates="receiver",
    )

    @property
    def daily_shift_schedules(self):
        return self.employee_shift_assignments

    @property
    def shifts(self):
        return self.shift_templates


class UserPositionAssignment(Base):
    __tablename__ = "user_position_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), nullable=False, index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="position_assignments", foreign_keys=[user_id])
    position = relationship("Position")


class UserSalaryAssignment(Base):
    __tablename__ = "user_salary_assignments"
    __table_args__ = (
        CheckConstraint(
            "monthly_salary >= 0",
            name="ck_user_salary_assignments_monthly_salary_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    monthly_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="salary_assignments", foreign_keys=[user_id])


class UserEmploymentMovement(Base):
    __tablename__ = "user_employment_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    old_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    change_batch_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )

    user = relationship("User", back_populates="employment_movements", foreign_keys=[user_id])
