from uuid import UUID

from calendar import monthrange, day_name
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.capabilities import is_staff_user
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.time import ensure_utc, month_bounds_utc, to_local, utc_now
from app.models.attendance import (
    AttendanceRecord,
    DepartmentRosterDay,
    EmployeeShiftAssignment,
    Holiday,
    OvertimeRequest,
    OvertimeRequestApprover,
    ShiftTemplate,
    ShiftSwapRequest,
)
from app.models.department import Department
from app.models.leave import LeaveRequestStatus
from app.models.user import User
from app.repositories.attendance import (
    AttendanceRecordRepository,
    DepartmentRosterDayRepository,
    EmployeeShiftAssignmentRepository,
    HolidayRepository,
    OvertimeRepository,
    ShiftTemplateRepository,
    ShiftSwapRepository,
)
from app.repositories.leave import LeaveRequestRepository
from app.repositories.departments import DepartmentRepository
from app.repositories.users import UserRepository
from app.services.notifications import create_notification_if_possible
from app.services.attendance_rules import evaluate_attendance_day
from app.schemas.attendance import (
    AttendanceRecordRead,
    AttendanceRecordCreateRequest,
    AttendanceRecordUpdateRequest,
    AttendanceSummaryDayRead,
    AttendanceSummaryLeaveRead,
    AttendanceSummaryRead,
    DepartmentScheduleUpdateRequest,
    UserShiftPolicyUpdateRequest,
    DepartmentRosterDayCreateRequest,
    EmployeeShiftAssignmentCreateRequest,
    EmployeeShiftAssignmentCopyPreviousMonthRequest,
    EmployeeShiftAssignmentCopyPreviousMonthResponse,
    EmployeeShiftAssignmentGenerateMonthRequest,
    EmployeeShiftAssignmentGenerateMonthResponse,
    EmployeeShiftAssignmentRead,
    EmployeeShiftAssignmentUpdateRequest,
    HolidayCreateRequest,
    HolidayRead,
    HolidayUpdateRequest,
    OvertimeApproverAssignmentRead,
    OvertimeRequestCreateRequest,
    OvertimeRequestScope,
    OvertimeRequestRespondRequest,
    ShiftTemplateCreateRequest,
    ShiftSwapRequestCreateRequest,
    ShiftSwapRequestRespondRequest,
    ShiftTemplateUpdateRequest,
)
from app.schemas.user import UserRead

# Backward-compatible test hook: older tests monkeypatch this symbol.
OvertimeApproverRepository = None


def _display_user_name(user: User | None) -> str:
    if user is None:
        return "A user"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return full_name or user.email


def _month_window(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    last_day = monthrange(year, month)[1]
    end = date(year, month, last_day)
    return start, end


def _ensure_aware(value: datetime) -> datetime:
    return ensure_utc(value)


def _validate_holiday_date(day: int, month: int, year: int | None) -> None:
    validation_year = year if year is not None else 2000
    try:
        date(validation_year, month, day)
    except ValueError as exc:
        raise BadRequestError("Holiday date is invalid.") from exc


async def _ensure_holiday_date_available(
    repository: HolidayRepository,
    *,
    day: int,
    month: int,
    year: int | None,
    exclude_id: int | None = None,
) -> None:
    conflicting_holiday = await repository.find_conflict(
        day=day,
        month=month,
        year=year,
        exclude_id=exclude_id,
    )
    if conflicting_holiday is None:
        return
    if conflicting_holiday.year is None:
        raise ConflictError("A recurring holiday already exists for this date.")
    raise ConflictError("A holiday already exists for this date.")


async def _build_overtime_approval_pool(session: AsyncSession, user: User) -> list[User]:
    user_repository = UserRepository(session)
    if user.level_1_approver_id is not None:
        primary_approver = await user_repository.get_by_id(user.level_1_approver_id)
        if primary_approver is None or not primary_approver.is_active:
            raise NotFoundError("Level 1 approver is not available for this user.")
        if primary_approver.id == user.id:
            raise ConflictError("Level 1 approver cannot be the same as the requester.")
        return [primary_approver]

    # Backward-compatible fallback for legacy department-based approver config.
    if OvertimeApproverRepository is None or user.department_id is None:
        raise NotFoundError("No Level 1 approver is configured for this user.")
    legacy_assignment = await OvertimeApproverRepository(session).get_by_department_id(
        user.department_id
    )
    if legacy_assignment is None:
        raise NotFoundError("No Level 1 approver is configured for this user.")

    approver_ids: list[UUID] = []
    for approver_id in (
        legacy_assignment.department_approver_id,
        legacy_assignment.director_approver_id,
        legacy_assignment.president_approver_id,
        legacy_assignment.hr_approver_id,
    ):
        if approver_id is not None and approver_id not in approver_ids:
            approver_ids.append(approver_id)
    if not approver_ids:
        raise NotFoundError("No Level 1 approver is configured for this user.")

    approvers: list[User] = []
    for approver_id in approver_ids:
        approver = await user_repository.get_by_id(approver_id)
        if approver is None or not approver.is_active:
            raise NotFoundError("Overtime approver is not available for this user.")
        if approver.id == user.id:
            raise ConflictError("Overtime approver cannot be the same as the requester.")
        approvers.append(approver)
    return approvers


async def _get_overtime_backup_approver(session: AsyncSession, user: User) -> User | None:
    if user.level_2_approver_id is not None:
        backup_approver = await UserRepository(session).get_by_id(user.level_2_approver_id)
        if backup_approver is None or not backup_approver.is_active:
            raise NotFoundError("Level 2 approver is not available for this user.")
        if backup_approver.id == user.id:
            raise ConflictError("Level 2 approver cannot be the same as the requester.")
        if user.level_1_approver_id is not None and backup_approver.id == user.level_1_approver_id:
            raise ConflictError("Level 2 approver must be different from Level 1 approver.")
        return backup_approver

    return None


async def _get_department_with_shifts(
    session: AsyncSession, department_id: int
) -> Department:
    statement = (
        select(Department)
        .options(selectinload(Department.shift_templates))
        .where(Department.id == department_id)
    )
    result = await session.execute(statement)
    department = result.scalar_one_or_none()
    if department is None:
        raise NotFoundError("Department not found.")
    return department


async def _get_user_with_shifts(
    session: AsyncSession, user_id: UUID
) -> User:
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")
    return user


def _ensure_user_shift_template_allowed(user: User, shift_id: int) -> None:
    allowed_shift_ids = {shift.id for shift in user.shift_templates}
    if shift_id not in allowed_shift_ids:
        raise ConflictError("The selected shift template is not allowed for this user.")


async def list_shift_templates(session: AsyncSession) -> list[ShiftTemplate]:
    return await ShiftTemplateRepository(session).list()


async def create_shift_template(
    session: AsyncSession, payload: ShiftTemplateCreateRequest
) -> ShiftTemplate:
    repository = ShiftTemplateRepository(session)
    existing = await repository.get_by_identity(
        payload.description,
        payload.start_time,
        payload.end_time,
        payload.start_time_2,
        payload.end_time_2,
    )
    if existing is not None:
        raise ConflictError("A shift with the same times already exists.")

    shift = ShiftTemplate(
        description=payload.description,
        start_time=payload.start_time,
        end_time=payload.end_time,
        start_time_2=payload.start_time_2,
        end_time_2=payload.end_time_2,
        late_grace_minutes=payload.late_grace_minutes,
        is_active=payload.is_active,
    )
    return await repository.create(shift)


async def update_shift_template(
    session: AsyncSession, shift_id: int, payload: ShiftTemplateUpdateRequest
) -> ShiftTemplate:
    repository = ShiftTemplateRepository(session)
    shift = await repository.get_by_id(shift_id)
    if shift is None:
        raise NotFoundError("Shift not found.")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(shift, key, value)
    return await repository.save(shift)


async def delete_shift_template(session: AsyncSession, shift_id: int) -> str:
    repository = ShiftTemplateRepository(session)
    shift = await repository.get_by_id(shift_id)
    if shift is None:
        raise NotFoundError("Shift not found.")
    description = shift.description
    try:
        await repository.delete(shift)
    except IntegrityError as exc:
        raise ConflictError("Shift cannot be deleted while it is in use.") from exc
    return description


async def update_department_schedule(
    session: AsyncSession, department_id: int, payload: DepartmentScheduleUpdateRequest
) -> Department:
    department_repository = DepartmentRepository(session)
    shift_repository = ShiftTemplateRepository(session)
    department = await department_repository.get_by_id(department_id)
    if department is None:
        raise NotFoundError("Department not found.")

    selected_shifts: list[ShiftTemplate] = []
    for shift_id in dict.fromkeys(payload.shift_ids):
        shift = await shift_repository.get_by_id(shift_id)
        if shift is None:
            raise NotFoundError("Shift not found.")
        selected_shifts.append(shift)

    department.default_workweek = payload.workweek
    department.shift_templates.clear()
    department.shift_templates.extend(selected_shifts)
    await department_repository.save(department)
    return await _get_department_with_shifts(session, department_id)


async def get_department_schedule(
    session: AsyncSession, department_id: int
) -> Department:
    return await _get_department_with_shifts(session, department_id)


async def get_user_shift_policy(session: AsyncSession, user_id: UUID) -> User:
    return await _get_user_with_shifts(session, user_id)


async def update_user_shift_policy(
    session: AsyncSession, user_id: UUID, payload: UserShiftPolicyUpdateRequest
) -> User:
    user_repository = UserRepository(session)
    shift_repository = ShiftTemplateRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    selected_shifts: list[ShiftTemplate] = []
    for shift_id in dict.fromkeys(payload.shift_ids):
        shift = await shift_repository.get_by_id(shift_id)
        if shift is None:
            raise NotFoundError("Shift not found.")
        selected_shifts.append(shift)

    user.shift_templates.clear()
    user.shift_templates.extend(selected_shifts)
    await user_repository.save(user)
    return await _get_user_with_shifts(session, user_id)


async def list_daily_shift_records(
    session: AsyncSession, department_id: int, year: int, month: int
) -> list[DepartmentRosterDay]:
    return await DepartmentRosterDayRepository(session).list_for_department_month(
        department_id, year, month
    )


async def create_daily_shift_record(
    session: AsyncSession, payload: DepartmentRosterDayCreateRequest
) -> DepartmentRosterDay:
    repository = DepartmentRosterDayRepository(session)
    existing = await repository.get_by_department_date(
        payload.department_id, payload.date
    )
    if existing is not None:
        raise ConflictError("Daily shift record already exists for the selected date.")

    record = DepartmentRosterDay(
        date=payload.date,
        department_id=payload.department_id,
        is_approved=payload.is_approved,
    )
    record = await repository.create(record)
    if payload.schedule_ids:
        schedule_repo = EmployeeShiftAssignmentRepository(session)
        schedules = []
        for schedule_id in payload.schedule_ids:
            schedule = await schedule_repo.get_by_id(schedule_id)
            if schedule is None:
                raise NotFoundError("Daily shift schedule not found.")
            schedules.append(schedule)
        record.employee_shift_assignments.extend(schedules)
        record = await repository.save(record)
    return record


async def create_employee_shift_assignment(
    session: AsyncSession, payload: EmployeeShiftAssignmentCreateRequest
) -> EmployeeShiftAssignment:
    repository = EmployeeShiftAssignmentRepository(session)
    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(payload.user_id)
    if user is None:
        raise NotFoundError("User not found.")
    shift = await ShiftTemplateRepository(session).get_by_id(payload.shift_id)
    if shift is None:
        raise NotFoundError("Shift not found.")
    _ensure_user_shift_template_allowed(user, payload.shift_id)
    existing = await repository.get_by_user_date(payload.user_id, payload.date)
    if existing is not None:
        raise ConflictError("A shift assignment already exists for the selected employee and date.")
    schedule = EmployeeShiftAssignment(
        date=payload.date,
        user_id=payload.user_id,
        shift_template_id=payload.shift_id,
    )
    schedule = await repository.create(schedule)
    await create_notification_if_possible(
        session,
        recipient_id=payload.user_id,
        content=(
            f"You were assigned to shift {shift.description} on "
            f"{payload.date.isoformat()}."
        ),
        url=f"/attendance?year={payload.date.year}&month={payload.date.month}",
    )
    return schedule


async def copy_previous_month_employee_shift_assignments(
    session: AsyncSession,
    payload: EmployeeShiftAssignmentCopyPreviousMonthRequest,
) -> EmployeeShiftAssignmentCopyPreviousMonthResponse:
    repository = EmployeeShiftAssignmentRepository(session)
    user = await UserRepository(session).get_by_id(payload.user_id)
    if user is None:
        raise NotFoundError("User not found.")

    if payload.month == 1:
        source_year = payload.year - 1
        source_month = 12
    else:
        source_year = payload.year
        source_month = payload.month - 1

    source_assignments = await repository.list_for_user_month(
        payload.user_id, source_year, source_month
    )
    if not source_assignments:
        raise NotFoundError("No assignments found in the previous month to copy.")

    target_assignments = await repository.list_for_user_month(
        payload.user_id, payload.year, payload.month
    )
    for assignment in target_assignments:
        await repository.delete(assignment)

    copied_count = 0
    skipped_count = 0
    target_last_day = monthrange(payload.year, payload.month)[1]

    for source_assignment in source_assignments:
        day = source_assignment.date.day
        if day > target_last_day:
            skipped_count += 1
            continue

        copied_assignment = EmployeeShiftAssignment(
            date=date(payload.year, payload.month, day),
            user_id=payload.user_id,
            shift_template_id=source_assignment.shift_template_id,
        )
        await repository.create(copied_assignment)
        copied_count += 1

    return EmployeeShiftAssignmentCopyPreviousMonthResponse(
        copied_count=copied_count,
        skipped_count=skipped_count,
    )


async def generate_month_employee_shift_assignments(
    session: AsyncSession,
    payload: EmployeeShiftAssignmentGenerateMonthRequest,
) -> EmployeeShiftAssignmentGenerateMonthResponse:
    repository = EmployeeShiftAssignmentRepository(session)
    user = await UserRepository(session).get_by_id(payload.user_id)
    if user is None:
        raise NotFoundError("User not found.")
    allowed_templates = list(user.shift_templates)
    if not allowed_templates:
        raise ConflictError("The selected user does not have allowed shift templates configured.")

    selected_template: ShiftTemplate | None = None
    if payload.shift_id is not None:
        selected_template = next(
            (template for template in allowed_templates if template.id == payload.shift_id),
            None,
        )
        if selected_template is None:
            raise ConflictError("The selected shift template is not allowed for this user.")
    else:
        selected_template = next(
            (template for template in allowed_templates if template.is_active),
            allowed_templates[0],
        )

    workweek_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}

    generated_count = 0
    skipped_count = 0
    for day in range(1, monthrange(payload.year, payload.month)[1] + 1):
        current_date = date(payload.year, payload.month, day)
        weekday_name = day_name[current_date.weekday()]
        if weekday_name not in workweek_days:
            continue

        existing = await repository.get_by_user_date(payload.user_id, current_date)
        if existing is not None:
            skipped_count += 1
            continue

        await repository.create(
            EmployeeShiftAssignment(
                date=current_date,
                user_id=payload.user_id,
                shift_template_id=selected_template.id,
            )
        )
        generated_count += 1

    return EmployeeShiftAssignmentGenerateMonthResponse(
        generated_count=generated_count,
        skipped_count=skipped_count,
    )


async def list_employee_shift_assignments(
    session: AsyncSession, department_id: int, year: int, month: int
) -> list[EmployeeShiftAssignment]:
    return await EmployeeShiftAssignmentRepository(session).list_for_department_month(
        department_id, year, month
    )


async def delete_employee_shift_assignment(
    session: AsyncSession, schedule_id: int
) -> None:
    repository = EmployeeShiftAssignmentRepository(session)
    schedule = await repository.get_by_id(schedule_id)
    if schedule is None:
        raise NotFoundError("Daily shift schedule not found.")
    shift_description = (
        schedule.shift_template.description if schedule.shift_template is not None else "your shift"
    )
    schedule_date = schedule.date.isoformat()
    user_id = schedule.user_id
    await repository.delete(schedule)
    await create_notification_if_possible(
        session,
        recipient_id=user_id,
        content=(
            f"Your shift assignment ({shift_description}) on {schedule_date} was removed."
        ),
        url=f"/attendance?year={schedule.date.year}&month={schedule.date.month}",
    )


async def update_employee_shift_assignment(
    session: AsyncSession,
    schedule_id: int,
    payload: EmployeeShiftAssignmentUpdateRequest,
) -> EmployeeShiftAssignment:
    repository = EmployeeShiftAssignmentRepository(session)
    schedule = await repository.get_by_id(schedule_id)
    if schedule is None:
        raise NotFoundError("Daily shift schedule not found.")
    user = await UserRepository(session).get_by_id(schedule.user_id)
    if user is None:
        raise NotFoundError("User not found.")
    previous_shift_description = (
        schedule.shift_template.description if schedule.shift_template is not None else "previous shift"
    )
    shift = await ShiftTemplateRepository(session).get_by_id(payload.shift_id)
    if shift is None:
        raise NotFoundError("Shift not found.")
    _ensure_user_shift_template_allowed(user, payload.shift_id)
    schedule.shift_template_id = payload.shift_id
    schedule = await repository.save(schedule)
    await create_notification_if_possible(
        session,
        recipient_id=schedule.user_id,
        content=(
            f"Your shift on {schedule.date.isoformat()} was updated from "
            f"{previous_shift_description} to {shift.description}."
        ),
        url=f"/attendance?year={schedule.date.year}&month={schedule.date.month}",
    )
    return schedule


async def list_attendance_records(
    session: AsyncSession, user_id: UUID, year: int, month: int
) -> list[AttendanceRecord]:
    start_dt, end_dt = month_bounds_utc(year, month)
    return await AttendanceRecordRepository(session).list_for_user_range(
        user_id, start_dt, end_dt
    )


async def create_attendance_record(
    session: AsyncSession, payload: AttendanceRecordCreateRequest
) -> AttendanceRecord:
    user = await UserRepository(session).get_by_id(payload.user_id)
    if user is None:
        raise NotFoundError("User not found.")
    repository = AttendanceRecordRepository(session)
    if payload.raw_event_id:
        by_raw_event = await repository.get_by_raw_event_id(payload.raw_event_id)
        if by_raw_event is not None:
            raise ConflictError("Attendance record already exists.")
        deleted_raw_event = await repository.get_deleted_by_raw_event_id(payload.raw_event_id)
        if deleted_raw_event is not None:
            raise ConflictError("Attendance record was deleted and cannot be restored.")
    duplicate = await repository.get_duplicate(
        payload.user_id, _ensure_aware(payload.timestamp), payload.punch
    )
    if duplicate is not None:
        raise ConflictError("Attendance record already exists.")
    record = AttendanceRecord(
        user_id=payload.user_id,
        device_user_id=payload.device_user_id,
        raw_event_id=payload.raw_event_id,
        timestamp=_ensure_aware(payload.timestamp),
        punch=payload.punch,
    )
    return await repository.create(record)


async def sync_device_attendance(
    session: AsyncSession,
    device_user_id: int,
    timestamp: datetime,
    punch: Literal["IN", "OUT"],
    raw_event_id: str | None = None,
) -> AttendanceRecord:
    user_repository = UserRepository(session)
    users = await user_repository.list(include_superusers=True)
    user = next((candidate for candidate in users if candidate.biometric_uid == device_user_id), None)
    if user is None:
        raise NotFoundError("No user is mapped to the provided biometric UID.")
    return await create_attendance_record(
        session,
        AttendanceRecordCreateRequest(
            user_id=user.id,
            device_user_id=device_user_id,
            raw_event_id=raw_event_id,
            timestamp=timestamp,
            punch=punch,
        ),
    )


async def update_attendance_record(
    session: AsyncSession, record_id: int, payload: AttendanceRecordUpdateRequest
) -> AttendanceRecord:
    repository = AttendanceRecordRepository(session)
    record = await repository.get_by_id(record_id)
    if record is None:
        raise NotFoundError("Attendance record not found.")
    data = payload.model_dump(exclude_unset=True)
    if "timestamp" in data and data["timestamp"] is not None:
        record.timestamp = _ensure_aware(data["timestamp"])
    if "punch" in data and data["punch"] is not None:
        record.punch = data["punch"]
    return await repository.save(record)


async def delete_attendance_record(session: AsyncSession, record_id: int) -> None:
    repository = AttendanceRecordRepository(session)
    record = await repository.get_by_id(record_id)
    if record is None:
        raise NotFoundError("Attendance record not found.")
    await repository.delete(record, tombstone_raw_event_id=record.raw_event_id)


async def list_holidays(session: AsyncSession, year: int | None = None) -> list[Holiday]:
    return await HolidayRepository(session).list(year=year)


async def create_holiday(session: AsyncSession, payload: HolidayCreateRequest) -> Holiday:
    _validate_holiday_date(payload.day, payload.month, payload.year)
    repository = HolidayRepository(session)
    await _ensure_holiday_date_available(
        repository,
        day=payload.day,
        month=payload.month,
        year=payload.year,
    )
    holiday = Holiday(
        name=payload.name,
        day=payload.day,
        month=payload.month,
        year=payload.year,
    )
    return await repository.create(holiday)


async def update_holiday(
    session: AsyncSession, holiday_id: int, payload: HolidayUpdateRequest
) -> Holiday:
    repository = HolidayRepository(session)
    holiday = await repository.get_by_id(holiday_id)
    if holiday is None:
        raise NotFoundError("Holiday not found.")
    data = payload.model_dump(exclude_unset=True)
    updated_day = data.get("day", holiday.day)
    updated_month = data.get("month", holiday.month)
    updated_year = data.get("year", holiday.year)
    _validate_holiday_date(updated_day, updated_month, updated_year)
    await _ensure_holiday_date_available(
        repository,
        day=updated_day,
        month=updated_month,
        year=updated_year,
        exclude_id=holiday_id,
    )
    for key, value in data.items():
        setattr(holiday, key, value)
    return await repository.save(holiday)


async def delete_holiday(session: AsyncSession, holiday_id: int) -> str:
    repository = HolidayRepository(session)
    holiday = await repository.get_by_id(holiday_id)
    if holiday is None:
        raise NotFoundError("Holiday not found.")
    holiday_label = f"{holiday.name} - {holiday.month}/{holiday.day}"
    await repository.delete(holiday)
    return holiday_label


async def list_overtime_requests(
    session: AsyncSession,
    *,
    current_user_id: UUID,
    current_user_is_staff: bool,
    scope: OvertimeRequestScope | None = None,
    user_id: UUID | None = None,
    approver_id: UUID | None = None,
    year: int | None = None,
    month: int | None = None,
    status: str | None = None,
    department_id: int | None = None,
    query: str | None = None,
) -> list[OvertimeRequest]:
    scope_label: OvertimeRequestScope
    if scope is not None:
        scope_label = scope
    elif user_id is not None:
        scope_label = "mine"
    elif approver_id is not None:
        scope_label = "approvals"
    elif current_user_is_staff:
        scope_label = "all"
    else:
        scope_label = "mine"

    selected_user_id = user_id
    selected_approver_id = approver_id

    if scope_label == "all":
        if not current_user_is_staff:
            raise PermissionDeniedError("You do not have permission to view all overtime requests.")
    elif scope_label == "approvals":
        if selected_approver_id is None:
            selected_approver_id = current_user_id
        elif selected_approver_id != current_user_id and not current_user_is_staff:
            raise PermissionDeniedError("You do not have permission to view this approver's requests.")
    else:
        if selected_user_id is None:
            selected_user_id = current_user_id
        elif selected_user_id != current_user_id and not current_user_is_staff:
            raise PermissionDeniedError("You do not have permission to view this user's requests.")

    return await OvertimeRepository(session).list(
        user_id=selected_user_id if scope_label != "approvals" else None,
        approver_id=selected_approver_id if scope_label != "mine" else None,
        year=year,
        month=month,
        status=status,
        department_id=department_id,
        query=query,
    )


async def get_my_overtime_approver_assignment(
    session: AsyncSession, current_user: User
) -> OvertimeApproverAssignmentRead:
    approvers = await _build_overtime_approval_pool(session, current_user)
    approver = approvers[0] if approvers else None
    return OvertimeApproverAssignmentRead(
        approver_id=approver.id if approver is not None else None,
        approver=UserRead.model_validate(approver) if approver is not None else None,
        approver_ids=[item.id for item in approvers],
        approvers=[UserRead.model_validate(item) for item in approvers],
    )


async def create_overtime_request(
    session: AsyncSession, current_user: User, payload: OvertimeRequestCreateRequest
) -> OvertimeRequest:
    user = await UserRepository(session).get_by_id(payload.user_id)
    if user is None:
        raise NotFoundError("User not found.")
    existing_overtime = await OvertimeRepository(session).get_active_for_user_date(
        payload.user_id,
        payload.date,
        statuses=(
            OvertimeRequest.Status.PENDING.value,
            OvertimeRequest.Status.APPROVED.value,
        ),
    )
    if existing_overtime is not None:
        raise ConflictError("An active overtime request already exists for this date.")
    existing_leave = await LeaveRequestRepository(session).get_active_for_user_date(
        payload.user_id,
        payload.date,
        statuses=(
            LeaveRequestStatus.PENDING.value,
            LeaveRequestStatus.APPROVED.value,
        ),
    )
    if existing_leave is not None:
        raise ConflictError("An active leave request already exists for this date.")
    approvers = await _build_overtime_approval_pool(session, user)
    if not approvers:
        raise NotFoundError("No overtime approver is configured for this user.")
    first_approver = approvers[0]
    overtime = OvertimeRequest(
        user_id=payload.user_id,
        approver_id=first_approver.id,
        info=payload.info,
        date=payload.date,
        escalated_to_backup_at=None,
        escalated_to_backup_by_id=None,
        status=OvertimeRequest.Status.PENDING.value,
        approver_pool=[
            OvertimeRequestApprover(
                approver_id=approver.id,
                status=OvertimeRequest.Status.PENDING.value,
            )
            for approver in approvers
        ],
    )
    overtime = await OvertimeRepository(session).create(overtime)
    requester_name = _display_user_name(user)
    for approver in approvers:
        await create_notification_if_possible(
            session,
            recipient_id=approver.id,
            sender_id=current_user.id,
            content=f"{requester_name} filed an overtime request for {overtime.date.isoformat()}.",
            url=(
                f"/hr/overtime-management?scope=approvals&status=PENDING"
                f"&month={overtime.date.month}&year={overtime.date.year}"
            ),
        )
    return overtime


async def escalate_overtime_request(
    session: AsyncSession,
    overtime_id: int,
    current_user: User,
) -> OvertimeRequest:
    repository = OvertimeRepository(session)
    overtime = await repository.get_by_id(overtime_id)
    if overtime is None:
        raise NotFoundError("Overtime request not found.")
    if overtime.status != OvertimeRequest.Status.PENDING.value:
        raise ConflictError("Only pending overtime requests can be escalated.")
    if overtime.escalated_to_backup_at is not None:
        raise ConflictError("Overtime request is already escalated to the backup approver.")

    requester = overtime.user
    if requester is None:
        raise NotFoundError("Request owner not found.")
    backup_approver = await _get_overtime_backup_approver(session, requester)
    if backup_approver is None:
        raise ConflictError("No Level 2 backup approver is configured for this request.")
    if backup_approver.id == overtime.user_id:
        raise ConflictError("Level 2 approver cannot be the same as the requester.")
    if overtime.approver_id == backup_approver.id:
        raise ConflictError("Overtime request is already assigned to the backup approver.")

    now = utc_now()
    for assignment in overtime.approver_pool:
        if assignment.status == OvertimeRequest.Status.PENDING.value:
            assignment.status = OvertimeRequest.Status.CANCELLED.value
            assignment.acted_at = now

    backup_assignment = next(
        (
            assignment
            for assignment in overtime.approver_pool
            if assignment.approver_id == backup_approver.id
        ),
        None,
    )
    if backup_assignment is None:
        overtime.approver_pool.append(
            OvertimeRequestApprover(
                approver_id=backup_approver.id,
                status=OvertimeRequest.Status.PENDING.value,
            )
        )
    else:
        backup_assignment.status = OvertimeRequest.Status.PENDING.value
        backup_assignment.acted_at = None

    overtime.approver_id = backup_approver.id
    overtime.escalated_to_backup_at = now
    overtime.escalated_to_backup_by_id = current_user.id
    overtime = await repository.save(overtime)

    requester_name = _display_user_name(overtime.user)
    await create_notification_if_possible(
        session,
        recipient_id=backup_approver.id,
        sender_id=current_user.id,
        content=(
            f"{requester_name}'s overtime request for {overtime.date.isoformat()} "
            "was escalated to you as backup approver."
        ),
        url=(
            f"/hr/overtime-management?scope=approvals&status=PENDING"
            f"&month={overtime.date.month}&year={overtime.date.year}"
        ),
    )
    return overtime


async def respond_to_overtime_request(
    session: AsyncSession,
    overtime_id: int,
    approver_id: UUID,
    payload: OvertimeRequestRespondRequest,
) -> OvertimeRequest:
    repository = OvertimeRepository(session)
    overtime = await repository.get_by_id(overtime_id)
    if overtime is None:
        raise NotFoundError("Overtime request not found.")
    if overtime.user_id == approver_id:
        raise PermissionDeniedError("You cannot review your own overtime request.")
    current_pool_assignment = next(
        (
            assignment
            for assignment in overtime.approver_pool
            if assignment.approver_id == approver_id
        ),
        None,
    )
    if current_pool_assignment is None:
        raise PermissionDeniedError("You do not have permission to respond to this request.")
    if current_pool_assignment.status != OvertimeRequest.Status.PENDING.value:
        raise ConflictError("This overtime request has already been decided by you.")
    if overtime.status != OvertimeRequest.Status.PENDING.value:
        raise ConflictError("This overtime request has already been decided.")
    final_status = (
        OvertimeRequest.Status.APPROVED.value
        if payload.response == "APPROVE"
        else OvertimeRequest.Status.REJECTED.value
    )
    current_pool_assignment.status = final_status
    current_pool_assignment.acted_at = datetime.now(UTC)
    for assignment in overtime.approver_pool:
        if assignment is current_pool_assignment:
            continue
        if assignment.status == OvertimeRequest.Status.PENDING.value:
            assignment.status = final_status
    overtime.approver_id = approver_id
    overtime.status = final_status
    overtime = await repository.save(overtime)
    decision = "approved" if payload.response == "APPROVE" else "rejected"
    await create_notification_if_possible(
        session,
        recipient_id=overtime.user_id,
        sender_id=approver_id,
        content=(
            f"Your overtime request for {overtime.date.isoformat()} has been {decision}."
        ),
        url=f"/overtime?month={overtime.date.month}&year={overtime.date.year}",
    )
    return overtime


async def cancel_overtime_request(
    session: AsyncSession, overtime_id: int, current_user: User
) -> OvertimeRequest:
    repository = OvertimeRepository(session)
    overtime = await repository.get_by_id(overtime_id)
    if overtime is None:
        raise NotFoundError("Overtime request not found.")
    if overtime.user_id != current_user.id and not is_staff_user(current_user):
        raise PermissionDeniedError("You are not allowed to cancel this overtime request.")
    if overtime.status != OvertimeRequest.Status.PENDING.value:
        raise ConflictError("Only pending overtime requests can be cancelled.")

    now = utc_now()
    overtime.status = OvertimeRequest.Status.CANCELLED.value
    for assignment in overtime.approver_pool:
        if assignment.status == OvertimeRequest.Status.PENDING.value:
            assignment.status = OvertimeRequest.Status.CANCELLED.value
            assignment.acted_at = now
    return await repository.save(overtime)


async def list_shift_swap_requests(
    session: AsyncSession, user_id: UUID | None = None, approver_id: UUID | None = None
) -> list[ShiftSwapRequest]:
    repository = ShiftSwapRepository(session)
    if user_id is not None:
        return await repository.list_for_user(user_id)
    if approver_id is not None:
        return await repository.list_for_approver(approver_id)
    return []


async def create_shift_swap_request(
    session: AsyncSession, payload: ShiftSwapRequestCreateRequest
) -> ShiftSwapRequest:
    user_repository = UserRepository(session)
    schedule_repository = EmployeeShiftAssignmentRepository(session)
    users: dict[UUID, User] = {}
    for user_id in (payload.requested_by_id, payload.requested_for_id, payload.approver_id):
        user = await user_repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        users[user_id] = user
    current_schedule = await schedule_repository.get_by_id(payload.current_schedule_id)
    requested_schedule = await schedule_repository.get_by_id(payload.requested_schedule_id)
    if current_schedule is None or requested_schedule is None:
        raise NotFoundError("Daily shift schedule not found.")
    swap = ShiftSwapRequest(
        requested_by_id=payload.requested_by_id,
        requested_for_id=payload.requested_for_id,
        current_schedule_id=payload.current_schedule_id,
        requested_schedule_id=payload.requested_schedule_id,
        approver_id=payload.approver_id,
        info=payload.info,
        status=ShiftSwapRequest.Status.PENDING.value,
    )
    swap = await ShiftSwapRepository(session).create(swap)
    requester_name = _display_user_name(users.get(payload.requested_by_id))
    await create_notification_if_possible(
        session,
        recipient_id=swap.approver_id,
        sender_id=swap.requested_by_id,
        content=f"{requester_name} filed a shift swap request that needs your review.",
        url=(
            f"/hr/user-attendance-management?tab=shifts&user={swap.requested_by_id}"
            f"&year={current_schedule.date.year}&month={current_schedule.date.month}"
        ),
    )
    await create_notification_if_possible(
        session,
        recipient_id=swap.requested_for_id,
        sender_id=swap.requested_by_id,
        content=f"{requester_name} requested to swap shift assignments with you.",
        url=(
            f"/attendance?year={current_schedule.date.year}"
            f"&month={current_schedule.date.month}"
        ),
    )
    return swap


async def respond_to_shift_swap_request(
    session: AsyncSession,
    swap_id: int,
    approver_id: UUID,
    payload: ShiftSwapRequestRespondRequest,
) -> ShiftSwapRequest:
    repository = ShiftSwapRepository(session)
    swap = await repository.get_by_id(swap_id)
    if swap is None:
        raise NotFoundError("Shift swap request not found.")
    if swap.approver_id != approver_id:
        raise PermissionDeniedError("You do not have permission to respond to this request.")
    swap.status = (
        ShiftSwapRequest.Status.APPROVED.value
        if payload.response == "APPROVE"
        else ShiftSwapRequest.Status.REJECTED.value
    )
    swap = await repository.save(swap)
    decision = "approved" if payload.response == "APPROVE" else "rejected"
    await create_notification_if_possible(
        session,
        recipient_id=swap.requested_by_id,
        sender_id=approver_id,
        content=f"Your shift swap request has been {decision}.",
        url="/attendance",
    )
    await create_notification_if_possible(
        session,
        recipient_id=swap.requested_for_id,
        sender_id=approver_id,
        content=f"A shift swap request involving you has been {decision}.",
        url="/attendance",
    )
    return swap


async def delete_shift_swap_request(session: AsyncSession, swap_id: int) -> None:
    repository = ShiftSwapRepository(session)
    swap = await repository.get_by_id(swap_id)
    if swap is None:
        raise NotFoundError("Shift swap request not found.")
    await repository.delete(swap)


async def get_attendance_summary(
    session: AsyncSession, user_id: UUID, year: int, month: int
) -> AttendanceSummaryRead:
    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    start, end = _month_window(year, month)
    total_days = (end - start).days + 1
    start_dt, end_dt = month_bounds_utc(year, month)
    attendance_records = await AttendanceRecordRepository(session).list_for_user_range(
        user_id,
        start_dt,
        end_dt,
    )
    assignments = await EmployeeShiftAssignmentRepository(session).list_for_user_month(
        user_id, year, month
    )
    holidays = await HolidayRepository(session).list(year=year)
    overtime = await OvertimeRepository(session).list_for_user(user_id)
    approved_leave_requests = await LeaveRequestRepository(session).list(
        user_id=user_id,
        status=LeaveRequestStatus.APPROVED.value,
        year=year,
        month=month,
    )

    records_by_day: dict[int, list[AttendanceRecord]] = {}
    for record in attendance_records:
        records_by_day.setdefault(to_local(record.timestamp).day, []).append(record)

    assignments_by_day: dict[int, EmployeeShiftAssignment] = {}
    for assignment in assignments:
        assignments_by_day[assignment.date.day] = assignment

    holidays_by_day: dict[int, list[Holiday]] = {}
    for holiday in holidays:
        if holiday.month == month and (holiday.year is None or holiday.year == year):
            holidays_by_day.setdefault(holiday.day, []).append(holiday)

    overtime_by_day = {
        overtime_request.date.day
        for overtime_request in overtime
        if overtime_request.status == OvertimeRequest.Status.APPROVED.value
        and overtime_request.date.year == year
        and overtime_request.date.month == month
    }
    approved_leave_by_day = {
        leave_request.leave_date.day: leave_request
        for leave_request in approved_leave_requests
    }

    summary_days: list[AttendanceSummaryDayRead] = []
    for day in range(1, total_days + 1):
        selected_date = date(year, month, day)
        assignment = assignments_by_day.get(day)
        leave_request = approved_leave_by_day.get(day)
        evaluation = evaluate_attendance_day(
            selected_date=selected_date,
            shift=assignment.shift_template if assignment is not None else None,
            records=records_by_day.get(day, []),
            is_holiday=day in holidays_by_day,
            approved_leave=leave_request,
        )
        summary_days.append(
            AttendanceSummaryDayRead(
                day=day,
                day_name=day_name[selected_date.weekday()],
                shift=EmployeeShiftAssignmentRead.model_validate(assignment)
                if assignment is not None
                else None,
                attendance_records=[
                    AttendanceRecordRead.model_validate(record)
                    for record in records_by_day.get(day, [])
                ],
                holidays=[
                    HolidayRead.model_validate(holiday)
                    for holiday in holidays_by_day.get(day, [])
                ],
                overtime_approved=day in overtime_by_day,
                approved_leave=AttendanceSummaryLeaveRead(
                    id=leave_request.id,
                    leave_date=leave_request.leave_date,
                    leave_type=leave_request.leave_type,
                    duration=getattr(leave_request, "duration", None) or "FULL_DAY",
                    approval_type=getattr(leave_request, "approval_type", None),
                    info=leave_request.info,
                )
                if leave_request is not None
                else None,
                status=evaluation.status,
                late_minutes=evaluation.late_minutes,
                scheduled_minutes=evaluation.scheduled_minutes,
                absence_units=evaluation.absence_units,
                deduction_units=evaluation.deduction_units,
                partial_record=evaluation.partial_record,
            )
        )

    return AttendanceSummaryRead(year=year, month=month, days=summary_days)


list_shifts = list_shift_templates
create_shift = create_shift_template
update_shift = update_shift_template
delete_shift = delete_shift_template
create_daily_shift_schedule = create_employee_shift_assignment
list_daily_shift_schedules = list_employee_shift_assignments
delete_daily_shift_schedule = delete_employee_shift_assignment
