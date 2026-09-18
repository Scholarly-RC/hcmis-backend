from datetime import date, datetime, time
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.models.base import Base

department_shift_templates = Table(
    "department_shifts",
    Base.metadata,
    Column("department_id", ForeignKey("departments.id"), primary_key=True),
    Column("shift_id", ForeignKey("shifts.id"), primary_key=True),
)

user_shift_templates = Table(
    "user_shifts",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("shift_id", ForeignKey("shifts.id"), primary_key=True),
)

department_roster_day_assignments = Table(
    "daily_shift_record_schedules",
    Base.metadata,
    Column("daily_shift_record_id", ForeignKey("daily_shift_records.id"), primary_key=True),
    Column("daily_shift_schedule_id", ForeignKey("daily_shift_schedules.id"), primary_key=True),
)


class ShiftTemplate(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    start_time_2: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time_2: Mapped[time | None] = mapped_column(Time, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    departments = relationship(
        "Department",
        secondary=department_shift_templates,
        back_populates="shift_templates",
    )
    users = relationship(
        "User",
        secondary=user_shift_templates,
        back_populates="shift_templates",
    )
    employee_shift_assignments = relationship(
        "EmployeeShiftAssignment", back_populates="shift_template"
    )


class EmployeeShiftAssignment(Base):
    __tablename__ = "daily_shift_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    shift_template_id: Mapped[int] = mapped_column("shift_id", ForeignKey("shifts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="employee_shift_assignments")
    shift_template = relationship("ShiftTemplate", back_populates="employee_shift_assignments")
    department_roster_days = relationship(
        "DepartmentRosterDay",
        secondary=department_roster_day_assignments,
        back_populates="employee_shift_assignments",
    )

    @property
    def shift_id(self) -> int:
        return self.shift_template_id

    @shift_id.setter
    def shift_id(self, value: int) -> None:
        self.shift_template_id = value

    @property
    def shift(self):
        return self.shift_template

    @shift.setter
    def shift(self, value) -> None:
        self.shift_template = value

    @property
    def records(self):
        return self.department_roster_days

    @records.setter
    def records(self, value) -> None:
        self.department_roster_days = value


class DepartmentRosterDay(Base):
    __tablename__ = "daily_shift_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    department = relationship("Department", back_populates="department_roster_days")
    employee_shift_assignments = relationship(
        "EmployeeShiftAssignment",
        secondary=department_roster_day_assignments,
        back_populates="department_roster_days",
    )

    @property
    def schedules(self):
        return self.employee_shift_assignments

    @schedules.setter
    def schedules(self, value) -> None:
        self.employee_shift_assignments = value


class Holiday(Base):
    __tablename__ = "holidays"
    __table_args__ = (
        CheckConstraint("day >= 1 AND day <= 31", name="ck_holidays_day_range"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_holidays_month_range"),
        CheckConstraint("year IS NULL OR year >= 1900", name="ck_holidays_year_range"),
        Index(
            "uq_holidays_recurring_effective_date",
            "month",
            "day",
            unique=True,
            postgresql_where=text("year IS NULL"),
        ),
        Index(
            "uq_holidays_specific_effective_date",
            "year",
            "month",
            "day",
            unique=True,
            postgresql_where=text("year IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("raw_event_id", name="uq_attendance_records_raw_event_id"),
    )

    class Punch(str, PyEnum):
        TIME_IN = "IN"
        TIME_OUT = "OUT"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    device_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    raw_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    punch: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="attendance_records")


class DeletedAttendanceRecord(Base):
    __tablename__ = "deleted_attendance_records"
    __table_args__ = (
        UniqueConstraint("raw_event_id", name="uq_deleted_attendance_records_raw_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    raw_event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class OvertimeRequest(Base):
    __tablename__ = "overtime_requests"

    class Status(str, PyEnum):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        CANCELLED = "CANCELLED"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    escalated_to_backup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    escalated_to_backup_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=Status.PENDING.value, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", foreign_keys=[user_id], back_populates="overtime_requests")
    approver = relationship(
        "User", foreign_keys=[approver_id], back_populates="overtime_approvals"
    )
    escalated_to_backup_by = relationship("User", foreign_keys=[escalated_to_backup_by_id])
    approver_pool = relationship(
        "OvertimeRequestApprover",
        back_populates="overtime_request",
        cascade="all, delete-orphan",
    )

    @staticmethod
    def _display_name(user) -> str | None:
        if user is None:
            return None
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        return full_name or user.email

    @property
    def user_name(self) -> str | None:
        return self._display_name(self.user)

    @property
    def user_email(self) -> str | None:
        return self.user.email if self.user is not None else None

    @property
    def user_department_name(self) -> str | None:
        if self.user is None or self.user.department is None:
            return None
        return self.user.department.name

    @property
    def approver_name(self) -> str | None:
        return self._display_name(self.approver)


class OvertimeRequestApprover(Base):
    __tablename__ = "overtime_request_approvers"
    __table_args__ = (
        UniqueConstraint(
            "overtime_request_id",
            "approver_id",
            name="uq_overtime_request_approvers_overtime_request_id_approver_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    overtime_request_id: Mapped[int] = mapped_column(
        ForeignKey("overtime_requests.id"), nullable=False, index=True
    )
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=OvertimeRequest.Status.PENDING.value, nullable=False, index=True
    )
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    overtime_request = relationship("OvertimeRequest", back_populates="approver_pool")
    approver = relationship("User", foreign_keys=[approver_id])


class ShiftSwapRequest(Base):
    __tablename__ = "shift_swap_requests"

    class Status(str, PyEnum):
        PENDING = "PEND"
        APPROVED = "APP"
        REJECTED = "REJ"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    requested_for_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    current_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("daily_shift_schedules.id"), index=True
    )
    requested_schedule_id: Mapped[int] = mapped_column(
        ForeignKey("daily_shift_schedules.id"), index=True
    )
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    info: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(4), default=Status.PENDING.value, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    requested_by = relationship(
        "User", foreign_keys=[requested_by_id], back_populates="shift_swap_requests"
    )
    requested_for = relationship(
        "User", foreign_keys=[requested_for_id], back_populates="shift_swap_targets"
    )
    current_schedule = relationship(
        "EmployeeShiftAssignment", foreign_keys=[current_schedule_id]
    )
    requested_schedule = relationship(
        "EmployeeShiftAssignment", foreign_keys=[requested_schedule_id]
    )
    approver = relationship(
        "User", foreign_keys=[approver_id], back_populates="shift_swap_approvals"
    )


class BridgeCommand(Base):
    __tablename__ = "bridge_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True, default="queued")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class BridgeUserSnapshot(Base):
    __tablename__ = "bridge_user_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    biometric_uid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# Compatibility aliases while the database tables and older modules are phased out.
Shift = ShiftTemplate
DailyShiftSchedule = EmployeeShiftAssignment
DailyShiftRecord = DepartmentRosterDay
department_shifts = department_shift_templates
user_shifts = user_shift_templates
daily_shift_record_schedules = department_roster_day_assignments
