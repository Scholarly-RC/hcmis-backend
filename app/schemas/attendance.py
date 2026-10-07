from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from app.schemas.department import DepartmentRead
from app.schemas.user import UserRead


class ShiftTemplateRead(BaseModel):
    id: int
    description: str
    start_time: time | None = None
    end_time: time | None = None
    start_time_2: time | None = None
    end_time_2: time | None = None
    late_grace_minutes: int = Field(default=0, ge=0, le=240)
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("late_grace_minutes", mode="before")
    @classmethod
    def default_missing_grace(cls, value):
        return 0 if value is None else value

    model_config = ConfigDict(from_attributes=True)


class DepartmentShiftPolicyRead(BaseModel):
    id: int
    name: str
    code: str
    workweek: list[str] = Field(default_factory=list)
    is_active: bool
    shifts: list["ShiftTemplateRead"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class UserShiftPolicyRead(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    email: str
    is_active: bool
    shifts: list["ShiftTemplateRead"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ShiftTemplateCreateRequest(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    start_time: time
    end_time: time
    start_time_2: time | None = None
    end_time_2: time | None = None
    late_grace_minutes: int = Field(default=0, ge=0, le=240)
    is_active: bool = True


class ShiftTemplateUpdateRequest(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=255)
    start_time: time | None = None
    end_time: time | None = None
    start_time_2: time | None = None
    end_time_2: time | None = None
    late_grace_minutes: int | None = Field(default=None, ge=0, le=240)
    is_active: bool | None = None


class AttendanceRecordRead(BaseModel):
    id: int
    user_id: UUID
    device_user_id: int | None = None
    raw_event_id: str | None = None
    timestamp: datetime
    punch: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttendanceRecordCreateRequest(BaseModel):
    user_id: UUID
    device_user_id: int | None = None
    raw_event_id: str | None = None
    timestamp: datetime
    punch: Literal["IN", "OUT"]


class AttendanceRecordUpdateRequest(BaseModel):
    timestamp: datetime | None = None
    punch: Literal["IN", "OUT"] | None = None


class EmployeeShiftAssignmentRead(BaseModel):
    id: int
    date: date
    user_id: UUID
    shift_id: int
    user: UserRead | None = None
    shift: ShiftTemplateRead | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmployeeShiftAssignmentCreateRequest(BaseModel):
    date: date
    user_id: UUID
    shift_id: int


class EmployeeShiftAssignmentUpdateRequest(BaseModel):
    shift_id: int


class EmployeeShiftAssignmentCopyPreviousMonthRequest(BaseModel):
    user_id: UUID
    year: int
    month: int


class EmployeeShiftAssignmentCopyPreviousMonthResponse(BaseModel):
    copied_count: int
    skipped_count: int


class EmployeeShiftAssignmentGenerateMonthRequest(BaseModel):
    user_id: UUID
    year: int
    month: int
    shift_id: int | None = None


class EmployeeShiftAssignmentGenerateMonthResponse(BaseModel):
    generated_count: int
    skipped_count: int


class DepartmentRosterDayRead(BaseModel):
    id: int
    date: date
    department_id: int
    is_approved: bool
    department: DepartmentRead | None = None
    schedules: list[EmployeeShiftAssignmentRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DepartmentRosterDayCreateRequest(BaseModel):
    date: date
    department_id: int
    schedule_ids: list[int] = Field(default_factory=list)
    is_approved: bool = False


class DepartmentScheduleUpdateRequest(BaseModel):
    workweek: list[str] = Field(default_factory=list)
    shift_ids: list[int] = Field(default_factory=list)


class UserShiftPolicyUpdateRequest(BaseModel):
    shift_ids: list[int] = Field(default_factory=list)


class HolidayRead(BaseModel):
    id: int
    name: str
    day: int
    month: int
    year: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HolidayCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    day: int = Field(ge=1, le=31)
    month: int = Field(ge=1, le=12)
    year: int | None = Field(default=None, ge=1900, le=9999)

    @model_validator(mode="after")
    def validate_calendar_date(self):
        validation_year = self.year if self.year is not None else 2000
        date(validation_year, self.month, self.day)
        return self


class HolidayUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    day: int | None = Field(default=None, ge=1, le=31)
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=1900, le=9999)

    @model_validator(mode="after")
    def validate_calendar_date(self):
        if self.day is None and self.month is None and self.year is None:
            return self
        validation_year = self.year if self.year is not None else 2000
        validation_month = self.month if self.month is not None else 1
        validation_day = self.day if self.day is not None else 1
        date(validation_year, validation_month, validation_day)
        return self


class OvertimeApproverAssignmentRead(BaseModel):
    approver_id: UUID | None = None
    approver: UserRead | None = None
    approver_ids: list[UUID] = Field(default_factory=list)
    approvers: list[UserRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class OvertimeRequestApproverRead(BaseModel):
    id: int
    overtime_request_id: int
    approver_id: UUID
    status: str
    acted_at: datetime | None = None
    approver: UserRead | None = None

    model_config = ConfigDict(from_attributes=True)


class OvertimeRequestRead(BaseModel):
    id: int
    user_id: UUID
    approver_id: UUID
    info: str | None = None
    date: date
    escalated_to_backup_at: datetime | None = None
    escalated_to_backup_by_id: UUID | None = None
    status: str
    user_name: str | None = None
    user_email: str | None = None
    user_department_name: str | None = None
    approver_name: str | None = None
    approver_pool: list[OvertimeRequestApproverRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OvertimeRequestCreateRequest(BaseModel):
    user_id: UUID
    info: str | None = None
    date: date


class OvertimeRequestRespondRequest(BaseModel):
    response: Literal["APPROVE", "REJECT"]


OvertimeRequestScope = Literal["mine", "approvals", "all"]


class ShiftSwapRequestRead(BaseModel):
    id: int
    requested_by_id: UUID
    requested_for_id: UUID
    current_schedule_id: int
    requested_schedule_id: int
    approver_id: UUID
    info: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShiftSwapRequestCreateRequest(BaseModel):
    requested_by_id: UUID
    requested_for_id: UUID
    current_schedule_id: int
    requested_schedule_id: int
    approver_id: UUID
    info: str | None = None


class ShiftSwapRequestRespondRequest(BaseModel):
    response: Literal["APPROVE", "REJECT"]


class AttendanceSummaryDayRead(BaseModel):
    day: int
    day_name: str
    shift: EmployeeShiftAssignmentRead | None = None
    attendance_records: list[AttendanceRecordRead] = Field(default_factory=list)
    holidays: list[HolidayRead] = Field(default_factory=list)
    overtime_approved: bool = False
    approved_leave: "AttendanceSummaryLeaveRead | None" = None
    status: str = "NO_SHIFT"
    late_minutes: int = 0
    scheduled_minutes: int = 0
    absence_units: float = 0.0
    deduction_units: float = 0.0
    partial_record: bool = False


class AttendanceSummaryLeaveRead(BaseModel):
    id: int
    leave_date: date
    leave_type: str
    duration: Literal["FULL_DAY", "FIRST_HALF", "SECOND_HALF"] = "FULL_DAY"
    approval_type: Literal["PAID", "NON_PAID"] | None = None
    info: str | None = None


class AttendanceSummaryRead(BaseModel):
    year: int
    month: int
    days: list[AttendanceSummaryDayRead]


class BridgeUserRead(BaseModel):
    user_id: UUID
    biometric_uid: int
    first_name: str
    last_name: str
    is_active: bool


class BridgeUsersResponse(BaseModel):
    users: list[BridgeUserRead] = Field(default_factory=list)


class BridgeCommandSyncUsersCreateRequest(BaseModel):
    site_code: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)


class BridgeCommandScanUsersCreateRequest(BaseModel):
    site_code: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)


class BridgeCommandAckRequest(BaseModel):
    status: Literal["done", "failed"]
    message: str | None = None
    executed_at: datetime | None = None


class BridgeCommandRead(BaseModel):
    command_id: int
    site_code: str
    device_id: str
    type: str
    payload: dict = Field(default_factory=dict)
    status: str
    message: str | None = None
    created_at: datetime
    dispatched_at: datetime | None = None
    executed_at: datetime | None = None


class BridgeCommandsResponse(BaseModel):
    commands: list[BridgeCommandRead] = Field(default_factory=list)


class BridgeLogEventRequest(BaseModel):
    device_user_id: str
    timestamp: datetime
    status: int | None = None
    punch: int | None = None
    raw_event_id: str | None = None


class BridgeLogsRequest(BaseModel):
    site_code: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    events: list[BridgeLogEventRequest] = Field(default_factory=list)


class BridgeLogsResponse(BaseModel):
    accepted: int = 0
    duplicates: int = 0
    unknown_users: int = 0
    failed: int = 0


class BridgeHeartbeatRequest(BaseModel):
    site_code: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    agent_version: str | None = None
    device_reachable: bool
    last_sync_at: str | None = None


class BridgeHeartbeatResponse(BaseModel):
    status: str = "ok"


class BridgeBiometricSnapshotUser(BaseModel):
    biometric_uid: int
    name: str = ""


class BridgeBiometricSnapshotRequest(BaseModel):
    site_code: str = Field(min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    scanned_at: datetime | None = None
    users: list[BridgeBiometricSnapshotUser] = Field(default_factory=list)


class BridgeBiometricSnapshotResponse(BaseModel):
    status: str = "ok"
    stored_users: int = 0


class BridgeReconcileRow(BaseModel):
    key: str
    biometric_uid: int | None = None
    app_user_id: UUID | None = None
    app_name: str | None = None
    biometric_name: str | None = None
    present_in_app: bool
    present_in_biometric: bool


class BridgeReconcileResponse(BaseModel):
    site_code: str
    device_id: str
    rows: list[BridgeReconcileRow] = Field(default_factory=list)


ShiftRead = ShiftTemplateRead
DepartmentScheduleRead = DepartmentShiftPolicyRead
ShiftCreateRequest = ShiftTemplateCreateRequest
ShiftUpdateRequest = ShiftTemplateUpdateRequest
DailyShiftScheduleRead = EmployeeShiftAssignmentRead
DailyShiftScheduleCreateRequest = EmployeeShiftAssignmentCreateRequest
DailyShiftRecordRead = DepartmentRosterDayRead
DailyShiftRecordCreateRequest = DepartmentRosterDayCreateRequest
