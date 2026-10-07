from __future__ import annotations

import argparse
import asyncio
from calendar import monthrange
from datetime import date, time, timedelta
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.base  # noqa: F401
from app.core.config import settings
from app.core.security import hash_password
from app.core.time import combine_local, local_today
from app.db.session import async_session_maker
from app.models.attendance import (
    AttendanceRecord,
    EmployeeShiftAssignment,
    ShiftTemplate,
    user_shift_templates,
)
from app.models.payroll import ThirteenthMonthPayout
from app.models.user import User
from app.repositories.payroll import PayslipRepository
from app.schemas.payroll import PayslipCreateRequest
from app.services.payroll import get_or_create_payslip, toggle_payslip_release


TEST_EMAIL = "13th-month.qa@example.com"
TEST_PASSWORD = "Test1234!"
TEST_EMPLOYEE_NUMBER = "QA-13TH-MONTH"
TEST_FIRST_NAME = "13th Month"
TEST_LAST_NAME = "QA"
TEST_SALARY = Decimal("22000.00")
SHIFT_DESCRIPTION = "13th Month QA Shift"
SHIFT_START = time(9, 0)
SHIFT_END = time(18, 0)


def _parse_args() -> argparse.Namespace:
    today = local_today()
    parser = argparse.ArgumentParser(
        description="Seed a local QA account for testing 13th month pay."
    )
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--month", type=int, default=1)
    return parser.parse_args()


def _assert_local_database() -> None:
    hostname = urlparse(settings.database_url).hostname
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "Refusing to seed a non-local database. "
            f"DATABASE_URL resolves to host {hostname!r}."
        )


def _test_dates(year: int, month: int) -> tuple[date, date]:
    first_day = date(year, month, 1)
    first_monday = first_day + timedelta(days=(7 - first_day.weekday()) % 7)
    if first_monday.month != month or first_monday.day >= monthrange(year, month)[1]:
        raise ValueError("The selected month does not have two test weekdays.")
    return first_monday, first_monday + timedelta(days=1)


async def _ensure_user(session: AsyncSession, year: int, month: int) -> User:
    result = await session.execute(select(User).where(User.email == TEST_EMAIL))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=TEST_EMAIL,
            username=TEST_EMAIL,
            password_hash=hash_password(TEST_PASSWORD),
            first_name=TEST_FIRST_NAME,
            last_name=TEST_LAST_NAME,
            employee_number=TEST_EMPLOYEE_NUMBER,
            role="EMP",
            monthly_salary=TEST_SALARY,
            date_of_hiring=date(year, month, 1),
            is_active=True,
            is_superuser=False,
        )
        session.add(user)
        await session.flush()
    else:
        user.password_hash = hash_password(TEST_PASSWORD)
        user.first_name = TEST_FIRST_NAME
        user.last_name = TEST_LAST_NAME
        user.employee_number = TEST_EMPLOYEE_NUMBER
        user.role = "EMP"
        user.monthly_salary = TEST_SALARY
        user.date_of_hiring = date(year, month, 1)
        user.resignation_date = None
        user.is_active = True
        user.is_superuser = False
    return user


async def _ensure_shift(session: AsyncSession) -> ShiftTemplate:
    result = await session.execute(
        select(ShiftTemplate).where(
            ShiftTemplate.description == SHIFT_DESCRIPTION,
            ShiftTemplate.start_time == SHIFT_START,
            ShiftTemplate.end_time == SHIFT_END,
            ShiftTemplate.start_time_2.is_(None),
            ShiftTemplate.end_time_2.is_(None),
        )
    )
    shift = result.scalars().first()
    if shift is None:
        shift = ShiftTemplate(
            description=SHIFT_DESCRIPTION,
            start_time=SHIFT_START,
            end_time=SHIFT_END,
            is_active=True,
        )
        session.add(shift)
        await session.flush()
    else:
        shift.is_active = True
    return shift


async def _ensure_shift_policy(
    session: AsyncSession, user: User, shift: ShiftTemplate
) -> None:
    result = await session.execute(
        select(user_shift_templates).where(
            user_shift_templates.c.user_id == user.id,
            user_shift_templates.c.shift_id == shift.id,
        )
    )
    if result.first() is None:
        await session.execute(
            user_shift_templates.insert().values(user_id=user.id, shift_id=shift.id)
        )


async def _ensure_assignments(
    session: AsyncSession,
    user: User,
    shift: ShiftTemplate,
    dates: tuple[date, date],
) -> None:
    for selected_date in dates:
        result = await session.execute(
            select(EmployeeShiftAssignment).where(
                EmployeeShiftAssignment.user_id == user.id,
                EmployeeShiftAssignment.date == selected_date,
            )
        )
        assignments = list(result.scalars().all())
        if len(assignments) > 1:
            raise RuntimeError(
                f"Multiple shift assignments already exist for {TEST_EMAIL} on "
                f"{selected_date.isoformat()}."
            )
        if assignments:
            assignments[0].shift_template_id = shift.id
        else:
            session.add(
                EmployeeShiftAssignment(
                    date=selected_date,
                    user_id=user.id,
                    shift_template_id=shift.id,
                )
            )


async def _ensure_punches(session: AsyncSession, user: User, selected_date: date) -> None:
    punches = (
        ("in", time(9, 30), "IN"),
        ("out", time(17, 0), "OUT"),
    )
    for suffix, selected_time, punch in punches:
        raw_event_id = f"13th-month-qa-{selected_date.isoformat()}-{suffix}"
        result = await session.execute(
            select(AttendanceRecord).where(AttendanceRecord.raw_event_id == raw_event_id)
        )
        record = result.scalar_one_or_none()
        timestamp = combine_local(selected_date, selected_time)
        if record is None:
            session.add(
                AttendanceRecord(
                    user_id=user.id,
                    raw_event_id=raw_event_id,
                    timestamp=timestamp,
                    punch=punch,
                )
            )
        else:
            record.user_id = user.id
            record.timestamp = timestamp
            record.punch = punch


async def _ensure_released_payslip(
    session: AsyncSession, user: User, year: int, month: int
) -> int:
    payslip = await get_or_create_payslip(
        session,
        PayslipCreateRequest(
            user_id=user.id,
            month=month,
            year=year,
            period="2ND",
        ),
    )
    if payslip.released and payslip.salary != TEST_SALARY:
        raise RuntimeError(
            f"The seeded payslip {payslip.id} is already released with salary "
            f"{payslip.salary}; refusing to change it."
        )
    if not payslip.released:
        payslip.salary = TEST_SALARY
        payslip = await PayslipRepository(session).save(payslip)
        payslip = await toggle_payslip_release(session, payslip.id)
    return payslip.id


async def _seed(year: int, month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError("Month must be between 1 and 12.")
    if year < 2000:
        raise ValueError("Year must be 2000 or later.")
    if date(year, month, 1) > local_today():
        raise ValueError("The selected test month must not be in the future.")

    _assert_local_database()
    absence_date, late_date = _test_dates(year, month)
    async with async_session_maker() as session:
        user = await _ensure_user(session, year, month)
        shift = await _ensure_shift(session)
        await _ensure_shift_policy(session, user, shift)
        await _ensure_assignments(session, user, shift, (absence_date, late_date))
        await _ensure_punches(session, user, late_date)
        await session.commit()

        payslip_id = await _ensure_released_payslip(session, user, year, month)
        await session.commit()

        payout_result = await session.execute(
            select(ThirteenthMonthPayout).where(
                ThirteenthMonthPayout.user_id == user.id,
                ThirteenthMonthPayout.year == year,
            )
        )
        payout = payout_result.scalar_one_or_none()

    print("Seeded local 13th month QA data:")
    print(f"- login email: {TEST_EMAIL}")
    print(f"- login password: {TEST_PASSWORD}")
    print(f"- employee id: {user.id}")
    print(f"- year/month: {year}/{month:02d}")
    print(f"- released payslip id: {payslip_id}")
    print(f"- no-punch absence date: {absence_date.isoformat()}")
    print(
        f"- late/undertime date: {late_date.isoformat()} "
        "(IN 09:30, OUT 17:00; shift 09:00-18:00)"
    )
    if payout is None:
        print("- payout: not generated yet; use HR > 13th Month > Generate")
    else:
        print(f"- existing payout: {payout.id} ({payout.status})")
    print("Expected after generation:")
    print("- annual basic: 22,000.00")
    print("- absence deduction: 1,000.00")
    print("- late deduction: 55.56")
    print("- undertime deduction: 111.11")
    print("- eligible basic: 20,833.33")
    print("- 13th month gross: 1,736.11")


def main() -> None:
    args = _parse_args()
    asyncio.run(_seed(args.year, args.month))


if __name__ == "__main__":
    main()
