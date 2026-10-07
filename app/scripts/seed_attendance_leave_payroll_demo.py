"""Seed a repeatable attendance, leave, and payroll QA dataset."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.base  # noqa: F401
from app.core.config import settings
from app.core.security import hash_password
from app.core.time import app_timezone, local_today, utc_now
from app.db.session import async_session_maker
from app.models.attendance import AttendanceRecord, EmployeeShiftAssignment, ShiftTemplate
from app.models.leave import (
    LeaveCredit,
    LeaveRequest,
    LeaveRequestApprover,
    LeaveRequestStatus,
    LeaveTypePolicy,
)
from app.models.user import User, UserSalaryAssignment
from app.repositories.payroll import PayrollPolicyVersionRepository
from app.schemas.payroll import PayslipCreateRequest, PayrollPolicyOfficialSeedRequest
from app.services.attendance_payroll import sync_attendance_deductions
from app.services.payroll import get_or_create_payslip
from app.services.payroll_workflow import (
    PH_OFFICIAL_POLICY_BASELINE_EFFECTIVE_FROM,
    PH_POLICY_KEY,
    activate_policy_version,
    seed_ph_policy_official_core,
)


DEMO_SHIFT_DESCRIPTION = "QA Attendance Demo Shift"
DEMO_RAW_EVENT_PREFIX = "qa-attendance-demo-"
DEMO_LEAVE_INFO_PREFIX = "Attendance leave payroll demo"
DEMO_POLICY_LABEL = "PH-STATUTORY-ACTIVE-2025"
DEMO_SALARY = Decimal("22000.00")
DEMO_PASSWORD = "qweasz123"


def _assert_local_database() -> None:
    hostname = urlparse(settings.database_url).hostname
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "Refusing to seed a non-local database. "
            f"DATABASE_URL resolves to host {hostname!r}."
        )


def _demo_cutoff(today: date) -> tuple[int, int, str, int, int]:
    """Return a completed cutoff with enough dates for all demo scenarios."""

    if today.day >= 7:
        return today.year, today.month, "1ST", 1, 6

    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1
    return year, month, "2ND", 16, monthrange(year, month)[1]


def _demo_dates(today: date) -> tuple[int, int, str, list[date]]:
    year, month, period, start_day, end_day = _demo_cutoff(today)
    dates = [date(year, month, day) for day in range(start_day, end_day + 1)]
    if period == "1ST":
        selected = dates[:6]
    else:
        selected = dates[-6:]
    if len(selected) < 6:
        raise RuntimeError("Unable to find six dates for the attendance demo seed.")
    return year, month, period, selected


def _local_datetime(selected_date: date, selected_time: time) -> datetime:
    return datetime.combine(selected_date, selected_time, tzinfo=app_timezone())


async def _required_users(session: AsyncSession) -> tuple[User, User]:
    result = await session.execute(
        select(User).where(
            User.email.in_(
                [
                    "admin@example.com",
                    "hr@example.com",
                    "employee@example.com",
                    "admin@ndkc.edu.ph",
                    "hr@ndkc.edu.ph",
                    "employee@ndkc.edu.ph",
                ]
            )
        )
    )
    users = {user.email: user for user in result.scalars().all()}
    aliases = {
        "admin@example.com": ("admin@example.com", "admin@ndkc.edu.ph"),
        "hr@example.com": ("hr@example.com", "hr@ndkc.edu.ph"),
        "employee@example.com": ("employee@example.com", "employee@ndkc.edu.ph"),
    }
    resolved: dict[str, User] = {}
    for expected_email, candidates in aliases.items():
        user = next((users[email] for email in candidates if email in users), None)
        if user is not None:
            user.email = expected_email
            user.password_hash = hash_password(DEMO_PASSWORD)
            user.is_active = True
            resolved[expected_email] = user

    missing = sorted(email for email in aliases if email not in resolved)
    if missing:
        raise RuntimeError(
            "Expected seeded accounts were not found: "
            f"{', '.join(missing)}. Run make seed-initial first."
        )
    resolved["admin@example.com"].role = "HR"
    resolved["admin@example.com"].is_superuser = True
    resolved["hr@example.com"].role = "HR"
    resolved["employee@example.com"].role = "EMP"
    return resolved["hr@example.com"], resolved["employee@example.com"]


async def _ensure_salary(
    session: AsyncSession,
    employee: User,
    changed_by: User,
    effective_from: date,
) -> None:
    employee.monthly_salary = DEMO_SALARY
    employee.level_1_approver_id = changed_by.id

    result = await session.execute(
        select(UserSalaryAssignment).where(
            UserSalaryAssignment.user_id == employee.id,
            UserSalaryAssignment.effective_from == effective_from,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        session.add(
            UserSalaryAssignment(
                user_id=employee.id,
                monthly_salary=DEMO_SALARY,
                effective_from=effective_from,
                change_reason="Attendance leave payroll demo seed",
                changed_by=changed_by.id,
            )
        )
    else:
        assignment.monthly_salary = DEMO_SALARY
        assignment.effective_to = None
        assignment.change_reason = "Attendance leave payroll demo seed"
        assignment.changed_by = changed_by.id

    credit_result = await session.execute(
        select(LeaveCredit).where(LeaveCredit.user_id == employee.id)
    )
    credit = credit_result.scalar_one_or_none()
    if credit is None:
        session.add(
            LeaveCredit(
                user_id=employee.id,
                credits=Decimal("15.00"),
                used_credits=Decimal("3.00"),
            )
        )
    else:
        credit.credits = Decimal("15.00")
        credit.used_credits = Decimal("3.00")


async def _ensure_shift(session: AsyncSession) -> ShiftTemplate:
    result = await session.execute(
        select(ShiftTemplate).where(ShiftTemplate.description == DEMO_SHIFT_DESCRIPTION)
    )
    shift = result.scalar_one_or_none()
    if shift is None:
        shift = ShiftTemplate(description=DEMO_SHIFT_DESCRIPTION)
        session.add(shift)

    shift.start_time = time(8, 0)
    shift.end_time = time(16, 0)
    shift.start_time_2 = None
    shift.end_time_2 = None
    shift.late_grace_minutes = 10
    shift.is_active = True
    await session.flush()
    return shift


async def _ensure_leave_type(session: AsyncSession) -> LeaveTypePolicy:
    result = await session.execute(
        select(LeaveTypePolicy).where(LeaveTypePolicy.code == "emergency_leave")
    )
    leave_type = result.scalar_one_or_none()
    if leave_type is None:
        leave_type = LeaveTypePolicy(
            code="emergency_leave",
            name="Emergency Leave",
            max_credits=10,
            credit_mode="fixed",
        )
        session.add(leave_type)
    else:
        leave_type.name = "Emergency Leave"
        leave_type.max_credits = 10
        leave_type.credit_mode = "fixed"
    await session.flush()
    return leave_type


async def _ensure_policy(session: AsyncSession) -> int:
    repository = PayrollPolicyVersionRepository(session)
    policy = await repository.get_by_identity(PH_POLICY_KEY, DEMO_POLICY_LABEL)
    if policy is None:
        policy = await seed_ph_policy_official_core(
            session,
            PayrollPolicyOfficialSeedRequest(
                version_label=DEMO_POLICY_LABEL,
                effective_from=PH_OFFICIAL_POLICY_BASELINE_EFFECTIVE_FROM,
                overwrite_existing=False,
            ),
        )
    if not policy.is_active:
        policy = await activate_policy_version(session, policy.id)
    return policy.id


async def _clear_demo_rows(session: AsyncSession) -> None:
    await session.execute(
        delete(AttendanceRecord).where(
            AttendanceRecord.raw_event_id.like(f"{DEMO_RAW_EVENT_PREFIX}%")
        )
    )
    result = await session.execute(
        select(LeaveRequest).where(
            LeaveRequest.info.like(f"{DEMO_LEAVE_INFO_PREFIX}%")
        )
    )
    for leave_request in result.scalars().all():
        await session.delete(leave_request)
    await session.flush()


async def _ensure_assignments(
    session: AsyncSession,
    employee: User,
    shift: ShiftTemplate,
    dates: list[date],
) -> None:
    for selected_date in dates:
        result = await session.execute(
            select(EmployeeShiftAssignment).where(
                EmployeeShiftAssignment.user_id == employee.id,
                EmployeeShiftAssignment.date == selected_date,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment is None:
            session.add(
                EmployeeShiftAssignment(
                    user_id=employee.id,
                    date=selected_date,
                    shift_template_id=shift.id,
                )
            )
        else:
            assignment.shift_template_id = shift.id
    await session.flush()


async def _add_punch(
    session: AsyncSession,
    employee: User,
    selected_date: date,
    selected_time: time,
    punch: str,
    label: str,
) -> None:
    session.add(
        AttendanceRecord(
            user_id=employee.id,
            timestamp=_local_datetime(selected_date, selected_time),
            punch=punch,
            raw_event_id=f"{DEMO_RAW_EVENT_PREFIX}{selected_date.isoformat()}-{label}",
        )
    )


async def _add_leave(
    session: AsyncSession,
    employee: User,
    approver: User,
    leave_type: LeaveTypePolicy,
    selected_date: date,
    duration: str,
    approval_type: str,
    label: str,
) -> None:
    request = LeaveRequest(
        user_id=employee.id,
        leave_date=selected_date,
        leave_type=leave_type.code,
        duration=duration,
        approval_type=approval_type,
        info=f"{DEMO_LEAVE_INFO_PREFIX}: {label}",
        first_approver_id=approver.id,
        first_approver_status=LeaveRequestStatus.APPROVED.value,
        status=LeaveRequestStatus.APPROVED.value,
        first_approver_at=utc_now(),
    )
    session.add(request)
    await session.flush()
    session.add(
        LeaveRequestApprover(
            leave_request_id=request.id,
            approver_id=approver.id,
            status=LeaveRequestStatus.APPROVED.value,
            acted_at=utc_now(),
        )
    )


async def _seed() -> None:
    _assert_local_database()
    today = local_today()
    year, month, period, dates = _demo_dates(today)
    emergency_date, paid_half_date, unpaid_half_date, partial_date, late_date, absence_date = dates

    async with async_session_maker() as session:
        hr, employee = await _required_users(session)
        await _clear_demo_rows(session)
        await _ensure_salary(session, employee, hr, date(year, month, 1))
        shift = await _ensure_shift(session)
        leave_type = await _ensure_leave_type(session)
        await _ensure_assignments(session, employee, shift, dates)

        await _add_leave(
            session,
            employee,
            hr,
            leave_type,
            emergency_date,
            "FULL_DAY",
            "NON_PAID",
            "full-day emergency leave",
        )
        await _add_leave(
            session,
            employee,
            hr,
            leave_type,
            paid_half_date,
            "FIRST_HALF",
            "PAID",
            "paid first-half leave",
        )
        await _add_leave(
            session,
            employee,
            hr,
            leave_type,
            unpaid_half_date,
            "SECOND_HALF",
            "NON_PAID",
            "unpaid second-half leave",
        )

        await _add_punch(session, employee, paid_half_date, time(12, 0), "IN", "paid-half-in")
        await _add_punch(session, employee, paid_half_date, time(16, 0), "OUT", "paid-half-out")
        await _add_punch(session, employee, unpaid_half_date, time(8, 0), "IN", "unpaid-half-in")
        await _add_punch(session, employee, unpaid_half_date, time(12, 0), "OUT", "unpaid-half-out")
        await _add_punch(session, employee, partial_date, time(8, 0), "IN", "partial-in")
        await _add_punch(session, employee, late_date, time(8, 40), "IN", "late-in")
        await _add_punch(session, employee, late_date, time(16, 0), "OUT", "late-out")
        await session.flush()

        policy_id = await _ensure_policy(session)
        payslip = await get_or_create_payslip(
            session,
            PayslipCreateRequest(
                user_id=employee.id,
                month=month,
                year=year,
                period=period,
            ),
        )
        if payslip.released:
            raise RuntimeError(
                f"Demo payslip {payslip.id} is already released. "
                "Create a new draft or unreleased payslip before reseeding."
            )
        payslip.salary = DEMO_SALARY
        await session.flush()
        payslip = await sync_attendance_deductions(session, payslip.id)

        attendance_rows = [
            item
            for item in payslip.variable_deductions
            if item.source == "ATTENDANCE"
        ]
        await session.commit()

    print("Seeded attendance/leave/payroll demo:")
    print(f"- admin login: admin@example.com / {DEMO_PASSWORD}")
    print(f"- HR login: hr@example.com / {DEMO_PASSWORD}")
    print(f"- employee: {employee.email} / {DEMO_PASSWORD}")
    print(f"- salary: {DEMO_SALARY:.2f}")
    print(f"- shift: {DEMO_SHIFT_DESCRIPTION} (08:00-16:00, 10m grace)")
    print(f"- emergency full-day unpaid leave: {emergency_date}")
    print(f"- paid first-half leave: {paid_half_date}")
    print(f"- unpaid second-half leave: {unpaid_half_date}")
    print(f"- partial punch review: {partial_date}")
    print(f"- late punch: {late_date}")
    print(f"- absence: {absence_date}")
    print(f"- payslip: {month:02d}/{year} {period} (id={payslip.id})")
    print(f"- active payroll policy id: {policy_id}")
    print(f"- automatic attendance deduction rows: {len(attendance_rows)}")


def main() -> None:
    import asyncio

    asyncio.run(_seed())


if __name__ == "__main__":
    main()
