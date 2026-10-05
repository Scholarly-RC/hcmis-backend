from __future__ import annotations

import argparse
import asyncio
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.base  # noqa: F401
from app.core.config import settings
from app.core.time import local_today
from app.db.session import async_session_maker
from app.models.department import Department
from app.models.payroll import (
    PayslipVariableCompensation,
    PayslipVariableDeduction,
    Position,
    position_departments,
)
from app.models.user import User, UserPositionAssignment, UserSalaryAssignment
from app.repositories.payroll import PayslipRepository, PayrollPolicyVersionRepository
from app.schemas.payroll import (
    PayslipCreateRequest,
    PayslipVariableCompensationUpsertRequest,
    PayslipVariableDeductionUpsertRequest,
    PayrollPolicyOfficialSeedRequest,
)
from app.services.payroll import (
    add_payslip_variable_compensation,
    add_payslip_variable_deduction,
    get_or_create_payslip,
    get_settings,
    toggle_payslip_release,
)
from app.services.payroll_workflow import (
    PH_OFFICIAL_POLICY_BASELINE_EFFECTIVE_FROM,
    PH_POLICY_KEY,
    activate_policy_version,
    seed_ph_policy_official_core,
)
from app.services.reports import get_payroll_summary_report


POLICY_VERSION_LABEL = "PH-STATUTORY-ACTIVE-2025"
POSITION_CODE = "PAYQA"
ASSIGNMENT_EFFECTIVE_FROM = date(2025, 1, 1)
EMPLOYEE_FIXTURES = (
    {
        "email": "employee@example.com",
        "salary": Decimal("50000.00"),
        "first_compensation": Decimal("1500.00"),
        "first_deduction": Decimal("250.00"),
        "second_compensation": Decimal("3000.00"),
        "second_deduction": Decimal("750.00"),
    },
    {
        "email": "test@account.com",
        "salary": Decimal("42000.00"),
        "first_compensation": Decimal("1000.00"),
        "first_deduction": Decimal("200.00"),
        "second_compensation": Decimal("0.00"),
        "second_deduction": Decimal("500.00"),
    },
)


def _parse_args() -> argparse.Namespace:
    today = local_today()
    parser = argparse.ArgumentParser(
        description="Seed a local payroll dataset for Payroll Summary testing."
    )
    parser.add_argument("--month", type=int, default=today.month)
    parser.add_argument("--year", type=int, default=today.year)
    return parser.parse_args()


def _assert_local_database() -> None:
    hostname = urlparse(settings.database_url).hostname
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "Refusing to seed a non-local database. "
            f"DATABASE_URL resolves to host {hostname!r}."
        )


async def _get_required_users(session: AsyncSession) -> tuple[User, User, list[User]]:
    hr_result = await session.execute(
        select(User).where(User.email == "hr@example.com")
    )
    hr_user = hr_result.scalar_one_or_none()
    if hr_user is None:
        raise RuntimeError("Expected HR account hr@example.com was not found.")

    employee_result = await session.execute(
        select(User)
        .where(User.email.in_([fixture["email"] for fixture in EMPLOYEE_FIXTURES]))
        .order_by(User.email.asc())
    )
    employees = list(employee_result.scalars().all())
    employee_by_email = {employee.email: employee for employee in employees}
    missing = [
        fixture["email"]
        for fixture in EMPLOYEE_FIXTURES
        if fixture["email"] not in employee_by_email
    ]
    if missing:
        raise RuntimeError(f"Expected employee accounts were not found: {', '.join(missing)}")

    return hr_user, employee_by_email[EMPLOYEE_FIXTURES[0]["email"]], employees


async def _get_position(session: AsyncSession, department_id: int) -> Position:
    department_result = await session.execute(
        select(Department).where(Department.id == department_id)
    )
    department = department_result.scalar_one()
    result = await session.execute(select(Position).where(Position.code == POSITION_CODE))
    position = result.scalar_one_or_none()
    if position is None:
        position = Position(
            title="Payroll QA Analyst",
            code=POSITION_CODE,
            is_active=True,
        )
        session.add(position)
        await session.flush()

    association_result = await session.execute(
        select(position_departments.c.position_id).where(
            position_departments.c.position_id == position.id,
            position_departments.c.department_id == department.id,
        )
    )
    if association_result.scalar_one_or_none() is None:
        await session.execute(
            position_departments.insert().values(
                position_id=position.id,
                department_id=department.id,
            )
        )

    return position


async def _ensure_employee_assignments(
    session: AsyncSession,
    employee: User,
    position: Position,
    salary: Decimal,
    changed_by: User,
) -> None:
    employee.position_id = position.id
    employee.monthly_salary = salary

    salary_result = await session.execute(
        select(UserSalaryAssignment).where(
            UserSalaryAssignment.user_id == employee.id,
            UserSalaryAssignment.effective_from == ASSIGNMENT_EFFECTIVE_FROM,
        )
    )
    salary_assignment = salary_result.scalar_one_or_none()
    if salary_assignment is None:
        session.add(
            UserSalaryAssignment(
                user_id=employee.id,
                monthly_salary=salary,
                effective_from=ASSIGNMENT_EFFECTIVE_FROM,
                change_reason="Payroll Summary local QA seed",
                changed_by=changed_by.id,
            )
        )
    else:
        salary_assignment.monthly_salary = salary
        salary_assignment.effective_to = None
        salary_assignment.change_reason = "Payroll Summary local QA seed"
        salary_assignment.changed_by = changed_by.id

    position_result = await session.execute(
        select(UserPositionAssignment).where(
            UserPositionAssignment.user_id == employee.id,
            UserPositionAssignment.effective_from == ASSIGNMENT_EFFECTIVE_FROM,
        )
    )
    position_assignment = position_result.scalar_one_or_none()
    if position_assignment is None:
        session.add(
            UserPositionAssignment(
                user_id=employee.id,
                position_id=position.id,
                effective_from=ASSIGNMENT_EFFECTIVE_FROM,
                change_reason="Payroll Summary local QA seed",
                changed_by=changed_by.id,
            )
        )
    else:
        position_assignment.position_id = position.id
        position_assignment.effective_to = None
        position_assignment.change_reason = "Payroll Summary local QA seed"
        position_assignment.changed_by = changed_by.id


async def _ensure_policy(session: AsyncSession) -> int:
    repository = PayrollPolicyVersionRepository(session)
    policy = await repository.get_by_identity(PH_POLICY_KEY, POLICY_VERSION_LABEL)
    if policy is None:
        policy = await seed_ph_policy_official_core(
            session,
            PayrollPolicyOfficialSeedRequest(
                version_label=POLICY_VERSION_LABEL,
                effective_from=PH_OFFICIAL_POLICY_BASELINE_EFFECTIVE_FROM,
                overwrite_existing=False,
            ),
        )

    if not policy.is_active:
        policy = await activate_policy_version(session, policy.id)
    return policy.id


async def _ensure_variable_items(
    session: AsyncSession,
    payslip_id: int,
    *,
    compensation_name: str,
    compensation_amount: Decimal,
    deduction_name: str,
    deduction_amount: Decimal,
) -> None:
    compensation_result = await session.execute(
        select(PayslipVariableCompensation).where(
            PayslipVariableCompensation.payslip_id == payslip_id,
            PayslipVariableCompensation.name == compensation_name,
        )
    )
    if compensation_result.scalar_one_or_none() is None and compensation_amount:
        await add_payslip_variable_compensation(
            session,
            payslip_id,
            PayslipVariableCompensationUpsertRequest(
                name=compensation_name,
                amount=compensation_amount,
            ),
        )

    deduction_result = await session.execute(
        select(PayslipVariableDeduction).where(
            PayslipVariableDeduction.payslip_id == payslip_id,
            PayslipVariableDeduction.name == deduction_name,
        )
    )
    if deduction_result.scalar_one_or_none() is None and deduction_amount:
        await add_payslip_variable_deduction(
            session,
            payslip_id,
            PayslipVariableDeductionUpsertRequest(
                name=deduction_name,
                amount=deduction_amount,
            ),
        )


async def _ensure_payslip(
    session: AsyncSession,
    employee: User,
    month: int,
    year: int,
    period: str,
    *,
    compensation_name: str,
    compensation_amount: Decimal,
    deduction_name: str,
    deduction_amount: Decimal,
) -> int:
    payslip = await get_or_create_payslip(
        session,
        PayslipCreateRequest(
            user_id=employee.id,
            month=month,
            year=year,
            period=period,
        ),
    )
    await _ensure_variable_items(
        session,
        payslip.id,
        compensation_name=compensation_name,
        compensation_amount=compensation_amount,
        deduction_name=deduction_name,
        deduction_amount=deduction_amount,
    )

    payslip = await PayslipRepository(session).get_by_id(payslip.id)
    if payslip is None:
        raise RuntimeError(f"Unable to reload seeded {period} payslip.")
    if not payslip.released:
        await toggle_payslip_release(session, payslip.id)
    return payslip.id


async def _seed(month: int, year: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError("Month must be between 1 and 12.")
    if year < 2000:
        raise ValueError("Year must be 2000 or later.")

    _assert_local_database()
    async with async_session_maker() as session:
        hr_user, _, employees = await _get_required_users(session)
        operations_result = await session.execute(
            select(Department).where(Department.code == "OPS")
        )
        operations = operations_result.scalar_one_or_none()
        if operations is None:
            raise RuntimeError("Expected Operations department with code OPS was not found.")

        position = await _get_position(session, operations.id)
        for fixture in EMPLOYEE_FIXTURES:
            employee = next(item for item in employees if item.email == fixture["email"])
            await _ensure_employee_assignments(
                session,
                employee,
                position,
                fixture["salary"],
                hr_user,
            )
        await session.commit()

        settings_row = await get_settings(session)
        settings_row.automatic_deduction_schedule = "SECOND_CUTOFF_ONLY"
        await session.commit()
        policy_id = await _ensure_policy(session)

        payslip_ids: list[int] = []
        for fixture in EMPLOYEE_FIXTURES:
            employee = next(item for item in employees if item.email == fixture["email"])
            payslip_ids.extend(
                [
                    await _ensure_payslip(
                        session,
                        employee,
                        month,
                        year,
                        "1ST",
                        compensation_name="QA Transport Allowance",
                        compensation_amount=fixture["first_compensation"],
                        deduction_name="QA Adjustment",
                        deduction_amount=fixture["first_deduction"],
                    ),
                    await _ensure_payslip(
                        session,
                        employee,
                        month,
                        year,
                        "2ND",
                        compensation_name="QA Performance Bonus",
                        compensation_amount=fixture["second_compensation"],
                        deduction_name="QA Loan Repayment",
                        deduction_amount=fixture["second_deduction"],
                    ),
                ]
            )

        report = await get_payroll_summary_report(session, month, year)
        print("Seeded local Payroll Summary dataset:")
        print(f"- period: {month:02d}/{year}")
        print(f"- policy_version_id: {policy_id}")
        print(f"- position: {position.title} ({position.code})")
        print(f"- released_payslip_ids: {', '.join(str(item) for item in payslip_ids)}")
        print(f"- employee_count: {report['employee_count']}")
        for row in report["rows"]:
            user = row["user"]
            monthly = row["monthly_total"]
            print(
                f"- {user['email']}: gross={monthly['gross_pay']:.2f}, "
                f"deductions={monthly['total_deductions']:.2f}, "
                f"net={monthly['net_salary']:.2f}"
            )
        print(f"- totals: {report['totals']['monthly_total']}")


def main() -> None:
    args = _parse_args()
    asyncio.run(_seed(args.month, args.year))


if __name__ == "__main__":
    main()
