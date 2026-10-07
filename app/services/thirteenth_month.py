from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.time import combine_local, local_today, month_bounds_utc, to_local
from app.models.attendance import AttendanceRecord, EmployeeShiftAssignment, Holiday
from app.models.leave import LeaveRequest, LeaveRequestStatus
from app.models.special_requests import OfficialBusinessRequest, SpecialRequestStatus
from app.models.user import User
from app.repositories.attendance import (
    AttendanceRecordRepository,
    EmployeeShiftAssignmentRepository,
    HolidayRepository,
)
from app.repositories.leave import LeaveRequestRepository
from app.repositories.special_requests import OfficialBusinessRequestRepository


MONTHLY_TO_DAILY_DIVISOR = Decimal("22")
MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class ThirteenthMonthAttendanceTotals:
    absence_deductions: Decimal = Decimal("0.00")
    late_deductions: Decimal = Decimal("0.00")
    undertime_deductions: Decimal = Decimal("0.00")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM)


def _employment_date_applies(user: User, selected_date: date) -> bool:
    if user.date_of_hiring is not None and selected_date < user.date_of_hiring:
        return False
    if user.resignation_date is not None and selected_date > user.resignation_date:
        return False
    return True


def _is_holiday(selected_date: date, holidays: list[Holiday]) -> bool:
    return any(
        holiday.month == selected_date.month
        and holiday.day == selected_date.day
        and (holiday.year is None or holiday.year == selected_date.year)
        for holiday in holidays
    )


def _shift_intervals(assignment: EmployeeShiftAssignment) -> list[tuple[datetime, datetime]]:
    shift = assignment.shift_template
    if shift is None:
        raise ConflictError(
            f"Cannot calculate 13th month attendance for {assignment.date}: "
            "the assigned shift is missing."
        )

    intervals: list[tuple[datetime, datetime]] = []
    for start_time, end_time in (
        (shift.start_time, shift.end_time),
        (shift.start_time_2, shift.end_time_2),
    ):
        if start_time is None and end_time is None:
            continue
        if start_time is None or end_time is None:
            raise ConflictError(
                f"Cannot calculate 13th month attendance for {assignment.date}: "
                "the assigned shift has incomplete hours."
            )
        start = combine_local(assignment.date, start_time)
        end = combine_local(assignment.date, end_time)
        if end <= start:
            end += timedelta(days=1)
        intervals.append((start, end))

    if not intervals:
        raise ConflictError(
            f"Cannot calculate 13th month attendance for {assignment.date}: "
            "the assigned shift has no working hours."
        )
    return intervals


def _records_for_assignment(
    records: list[AttendanceRecord],
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, str]]:
    first_start = intervals[0][0]
    last_end = intervals[-1][1]
    window_start = first_start - timedelta(hours=6)
    window_end = last_end + timedelta(hours=6)
    selected: list[tuple[datetime, str]] = []
    for record in records:
        local_timestamp = to_local(record.timestamp)
        if window_start <= local_timestamp <= window_end:
            selected.append((local_timestamp, record.punch))
    selected.sort(key=lambda item: item[0])
    return selected


def calculate_attendance_deductions(
    *,
    user: User,
    year: int,
    monthly_salary_by_month: dict[int, Decimal],
    assignments: list[EmployeeShiftAssignment],
    attendance_records: list[AttendanceRecord],
    holidays: list[Holiday],
    leave_requests: list[LeaveRequest],
    official_business_requests: list[OfficialBusinessRequest],
) -> ThirteenthMonthAttendanceTotals:
    leaves_by_date = {item.leave_date: item for item in leave_requests}
    official_business_dates = {item.date for item in official_business_requests}
    assignments_by_date: dict[date, EmployeeShiftAssignment] = {}
    for assignment in assignments:
        if assignment.date in assignments_by_date:
            raise ConflictError(
                f"Cannot calculate 13th month attendance for {user.email}: "
                f"multiple shifts are assigned on {assignment.date}."
            )
        assignments_by_date[assignment.date] = assignment

    absence_total = Decimal("0.00")
    late_total = Decimal("0.00")
    undertime_total = Decimal("0.00")
    calculation_date = local_today()

    for selected_date, assignment in sorted(assignments_by_date.items()):
        if (
            selected_date.year != year
            or selected_date > calculation_date
            or not _employment_date_applies(user, selected_date)
        ):
            continue

        monthly_salary = monthly_salary_by_month.get(selected_date.month)
        if monthly_salary is None or monthly_salary <= 0:
            continue

        if _is_holiday(selected_date, holidays) or selected_date in official_business_dates:
            continue

        daily_rate = monthly_salary / MONTHLY_TO_DAILY_DIVISOR
        leave_request = leaves_by_date.get(selected_date)
        if leave_request is not None:
            if leave_request.approval_type == "NON_PAID":
                absence_total += daily_rate
            continue

        intervals = _shift_intervals(assignment)
        day_records = _records_for_assignment(attendance_records, intervals)
        if not day_records:
            absence_total += daily_rate
            continue

        first_in = next((timestamp for timestamp, punch in day_records if punch == "IN"), None)
        last_out = next(
            (timestamp for timestamp, punch in reversed(day_records) if punch == "OUT"),
            None,
        )
        if first_in is None or last_out is None:
            raise ConflictError(
                f"Cannot calculate 13th month attendance for {user.email}: "
                f"incomplete attendance punches on {selected_date}."
            )

        scheduled_minutes = Decimal(
            str(
                sum(
                    (interval_end - interval_start).total_seconds() / 60
                    for interval_start, interval_end in intervals
                )
            )
        )
        if scheduled_minutes <= 0:
            raise ConflictError(
                f"Cannot calculate 13th month attendance for {user.email}: "
                f"invalid shift duration on {selected_date}."
        )

        scheduled_start = intervals[0][0]
        scheduled_end = intervals[-1][1]
        late_minutes = Decimal(
            str(max((first_in - scheduled_start).total_seconds(), 0) / 60)
        )
        undertime_minutes = Decimal(
            str(max((scheduled_end - last_out).total_seconds(), 0) / 60)
        )
        minute_rate = daily_rate / scheduled_minutes
        late_total += minute_rate * late_minutes
        undertime_total += minute_rate * undertime_minutes

    return ThirteenthMonthAttendanceTotals(
        absence_deductions=_money(absence_total),
        late_deductions=_money(late_total),
        undertime_deductions=_money(undertime_total),
    )


async def calculate_thirteenth_month_attendance(
    session: AsyncSession,
    user: User,
    year: int,
    monthly_salary_by_month: dict[int, Decimal],
    *,
    holidays: list[Holiday] | None = None,
) -> ThirteenthMonthAttendanceTotals:
    start, end = month_bounds_utc(year, 1)[0], month_bounds_utc(year, 12)[1]
    assignments = await EmployeeShiftAssignmentRepository(session).list_for_user_year(
        user.id, year
    )
    attendance_records = await AttendanceRecordRepository(session).list_for_user_range(
        user.id, start, end
    )
    leave_requests = await LeaveRequestRepository(session).list(
        user_id=user.id,
        status=LeaveRequestStatus.APPROVED.value,
        year=year,
    )
    official_business_requests = await OfficialBusinessRequestRepository(session).list(
        user_id=user.id,
        status=SpecialRequestStatus.APPROVED.value,
        year=year,
    )
    selected_holidays = holidays
    if selected_holidays is None:
        selected_holidays = await HolidayRepository(session).list(year=year)

    return calculate_attendance_deductions(
        user=user,
        year=year,
        monthly_salary_by_month=monthly_salary_by_month,
        assignments=assignments,
        attendance_records=attendance_records,
        holidays=selected_holidays,
        leave_requests=leave_requests,
        official_business_requests=official_business_requests,
    )
