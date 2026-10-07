"""Automatic attendance deductions for draft payslips."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.time import day_bounds_utc, local_today, to_local
from app.models.leave import LeaveRequestStatus
from app.models.payroll import Payslip
from app.repositories.attendance import (
    AttendanceRecordRepository,
    EmployeeShiftAssignmentRepository,
    HolidayRepository,
)
from app.repositories.leave import LeaveRequestRepository
from app.repositories.payroll import PayslipRepository, PayslipVariableDeductionRepository
from app.services.attendance_rules import evaluate_attendance_day


MONTHLY_TO_DAILY_DIVISOR = Decimal("22")
ATTENDANCE_SOURCE = "ATTENDANCE"


def payslip_period_dates(payslip: Payslip) -> tuple[date, date]:
    if payslip.month is None or payslip.year is None or payslip.period not in {"1ST", "2ND"}:
        raise ValueError("Payslip month, year, and period are required for attendance deductions.")
    last_day = monthrange(payslip.year, payslip.month)[1]
    if payslip.period == "1ST":
        return date(payslip.year, payslip.month, 1), date(payslip.year, payslip.month, 15)
    return date(payslip.year, payslip.month, 16), date(payslip.year, payslip.month, last_day)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


async def calculate_attendance_deductions(
    session: AsyncSession,
    payslip: Payslip,
) -> list[dict]:
    """Return one source row per attendance exception in the payslip cutoff."""

    start_date, end_date = payslip_period_dates(payslip)
    if payslip.salary is None:
        return []

    start_utc = day_bounds_utc(start_date)[0]
    end_utc = day_bounds_utc(end_date)[1]
    assignments = await EmployeeShiftAssignmentRepository(session).list_for_user_month(
        payslip.user_id, payslip.year or start_date.year, payslip.month or start_date.month
    )
    records = await AttendanceRecordRepository(session).list_for_user_range(
        payslip.user_id, start_utc, end_utc
    )
    holidays = await HolidayRepository(session).list(year=payslip.year)
    leaves = await LeaveRequestRepository(session).list(
        user_id=payslip.user_id,
        status=LeaveRequestStatus.APPROVED.value,
        year=payslip.year,
        month=payslip.month,
    )

    assignments_by_date = {
        assignment.date: assignment
        for assignment in assignments
        if start_date <= assignment.date <= end_date
    }
    records_by_date: dict[date, list] = {}
    for record in records:
        records_by_date.setdefault(to_local(record.timestamp).date(), []).append(record)
    holiday_dates = {
        date(payslip.year or start_date.year, holiday.month, holiday.day)
        for holiday in holidays
        if holiday.month == (payslip.month or start_date.month)
        and (holiday.year is None or holiday.year == payslip.year)
        and holiday.day
        <= monthrange(payslip.year or start_date.year, payslip.month or start_date.month)[1]
    }
    leaves_by_date = {leave.leave_date: leave for leave in leaves}
    daily_rate = Decimal(str(payslip.salary)) / MONTHLY_TO_DAILY_DIVISOR
    today = local_today()
    rows: list[dict] = []

    cursor = start_date
    while cursor <= end_date:
        assignment = assignments_by_date.get(cursor)
        evaluation = evaluate_attendance_day(
            selected_date=cursor,
            shift=assignment.shift_template if assignment is not None else None,
            records=records_by_date.get(cursor, []),
            is_holiday=cursor in holiday_dates,
            approved_leave=leaves_by_date.get(cursor),
            reference_date=today,
        )
        if (
            evaluation.deduction_units > 0
            and not evaluation.partial_record
            and cursor < today
        ):
            amount = _money(daily_rate * evaluation.deduction_units)
            if amount > 0:
                rows.append(
                    {
                        "name": f"Attendance exception - {cursor.isoformat()}",
                        "amount": amount,
                        "source": ATTENDANCE_SOURCE,
                        "source_date": cursor,
                        "source_type": evaluation.status,
                    }
                )
        cursor += timedelta(days=1)
    return rows


async def sync_attendance_deductions(
    session: AsyncSession,
    payslip_id: int,
) -> Payslip:
    """Replace only attendance-generated rows, preserving manual deductions."""

    payslip = await PayslipRepository(session).get_by_id(payslip_id)
    if payslip is None:
        raise NotFoundError("Payslip not found.")
    if payslip.released:
        return payslip

    rows = await calculate_attendance_deductions(session, payslip)
    await PayslipVariableDeductionRepository(session).replace_attendance_for_payslip(
        payslip_id, rows
    )
    refreshed = await PayslipRepository(session).get_by_id(payslip_id)
    return refreshed or payslip
