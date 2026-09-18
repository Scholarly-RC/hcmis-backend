from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.time import local_today, utc_now
from app.models.payroll import (
    FixedCompensation,
    Mp2Enrollment,
    Position,
    PayrollSetting,
    Payslip,
    PayslipVariableCompensation,
    PayslipVariableDeduction,
    ThirteenthMonthAdjustment,
    ThirteenthMonthPayout,
)
from app.models.department import Department
from app.models.user import User
from app.repositories.departments import DepartmentRepository
from app.repositories.payroll import (
    FixedCompensationRepository,
    Mp2EnrollmentRepository,
    PositionRepository,
    PayrollSettingRepository,
    PayslipRepository,
    PayslipVariableCompensationRepository,
    PayslipVariableDeductionRepository,
    ThirteenthMonthAdjustmentRepository,
    ThirteenthMonthPayoutRepository,
)
from app.repositories.users import UserRepository
from app.repositories.users import UserSalaryAssignmentRepository
from app.services.notifications import create_notification_if_possible
from app.schemas.payroll import (
    FixedCompensationUpsertRequest,
    FixedCompensationUsersRequest,
    Mp2EnrollmentCreateRequest,
    Mp2EnrollmentUpdateRequest,
    PositionUpsertRequest,
    PayrollSettingUpdateRequest,
    PayslipCreateRequest,
    PayslipUpdateRequest,
    PayslipVariableCompensationUpsertRequest,
    PayslipVariableDeductionUpsertRequest,
    ThirteenthMonthAdjustmentCreateRequest,
    ThirteenthMonthGenerateRequest,
)


DEFAULT_DEDUCTION_CONFIG = [
    {
        "name": "SSS",
        "data": {
            "min_compensation": "0",
            "max_compensation": "999999",
            "min_contribution": "0",
            "max_contribution": "0",
            "contribution_difference": "0",
        },
    },
    {
        "name": "PHILHEALTH",
        "data": {
            "min_compensation": "0",
            "max_compensation": "999999",
            "min_contribution": "0",
            "max_contribution": "0",
            "rate": "0",
        },
    },
    {
        "name": "TAX",
        "data": {
            "compensation_range": "0",
            "percentage": "0",
            "base_tax": "0",
        },
    },
    {
        "name": "PAG-IBIG",
        "data": {"amount": "0"},
    },
]
MONTHLY_TO_DAILY_DIVISOR = Decimal("22")
SEMI_MONTHLY_DAYS = Decimal("10")


def _to_decimal(value: Decimal | int | str | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


async def get_settings(session: AsyncSession) -> PayrollSetting:
    repository = PayrollSettingRepository(session)
    settings = await repository.get_first()
    if settings is None:
        settings = PayrollSetting(
            id=1,
            deduction_config=DEFAULT_DEDUCTION_CONFIG,
            automatic_deduction_schedule="SECOND_CUTOFF_ONLY",
        )
        return await repository.create(settings)
    return settings


async def update_settings(
    session: AsyncSession, payload: PayrollSettingUpdateRequest
) -> PayrollSetting:
    settings = await get_settings(session)
    data = payload.model_dump(exclude_unset=True)
    for field_name, value in data.items():
        setattr(settings, field_name, value)
    return await PayrollSettingRepository(session).save(settings)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def resolve_mp2_effective_date(
    month: int | None,
    year: int | None,
    period: str | None,
) -> date:
    if month is None or year is None:
        return local_today()
    if period == "1ST":
        return date(year, month, 15)
    return date(year, month, monthrange(year, month)[1])


async def list_mp2_enrollments(
    session: AsyncSession,
    status: str | None = None,
) -> list[Mp2Enrollment]:
    return await Mp2EnrollmentRepository(session).list(status=status)


async def get_mp2_enrollment(session: AsyncSession, enrollment_id: int) -> Mp2Enrollment:
    enrollment = await Mp2EnrollmentRepository(session).get_by_id(enrollment_id)
    if enrollment is None:
        raise NotFoundError("MP2 enrollment not found.")
    return enrollment


async def create_mp2_enrollment(
    session: AsyncSession,
    payload: Mp2EnrollmentCreateRequest,
) -> Mp2Enrollment:
    if payload.effective_to is not None and payload.effective_to < payload.effective_from:
        raise ConflictError("Effective to date must be on or after effective from date.")
    user = await UserRepository(session).get_by_id(payload.user_id)
    if user is None:
        raise NotFoundError("User not found.")
    enrollment = Mp2Enrollment(
        user_id=payload.user_id,
        amount=payload.amount,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        status=payload.status,
        mp2_account_number=_normalize_optional_text(payload.mp2_account_number),
        notes=_normalize_optional_text(payload.notes),
    )
    return await Mp2EnrollmentRepository(session).create(enrollment)


async def update_mp2_enrollment(
    session: AsyncSession,
    enrollment_id: int,
    payload: Mp2EnrollmentUpdateRequest,
) -> Mp2Enrollment:
    enrollment = await get_mp2_enrollment(session, enrollment_id)
    data = payload.model_dump(exclude_unset=True)
    if "mp2_account_number" in data:
        data["mp2_account_number"] = _normalize_optional_text(data["mp2_account_number"])
    if "notes" in data:
        data["notes"] = _normalize_optional_text(data["notes"])
    next_effective_from = data.get("effective_from", enrollment.effective_from)
    next_effective_to = data.get("effective_to", enrollment.effective_to)
    if next_effective_to is not None and next_effective_to < next_effective_from:
        raise ConflictError("Effective to date must be on or after effective from date.")
    for field_name, value in data.items():
        setattr(enrollment, field_name, value)
    return await Mp2EnrollmentRepository(session).save(enrollment)


async def end_mp2_enrollment(
    session: AsyncSession,
    enrollment_id: int,
    effective_to: date,
) -> Mp2Enrollment:
    enrollment = await get_mp2_enrollment(session, enrollment_id)
    if effective_to < enrollment.effective_from:
        raise ConflictError("End date must be on or after effective from date.")
    enrollment.effective_to = effective_to
    enrollment.status = "ended"
    return await Mp2EnrollmentRepository(session).save(enrollment)


async def get_active_mp2_for_user(
    session: AsyncSession,
    user_id: UUID,
    effective_date: date,
) -> Mp2Enrollment | None:
    return await Mp2EnrollmentRepository(session).get_active_for_user_on(user_id, effective_date)


def list_deduction_config() -> list[dict]:
    return [item.copy() for item in DEFAULT_DEDUCTION_CONFIG]


def _semi_monthly_base_from_monthly(monthly_salary: Decimal) -> Decimal:
    daily_rate = monthly_salary / MONTHLY_TO_DAILY_DIVISOR
    return (daily_rate * SEMI_MONTHLY_DAYS).quantize(Decimal("0.01"))


async def list_positions(session: AsyncSession, department_id: int | None = None) -> list[Position]:
    return await PositionRepository(session).list(department_id=department_id)


async def _resolve_departments(
    session: AsyncSession, department_ids: list[int]
) -> list[Department]:
    department_repository = DepartmentRepository(session)
    departments = []
    for department_id in dict.fromkeys(department_ids):
        department = await department_repository.get_by_id(department_id)
        if department is None:
            raise NotFoundError("Department not found.")
        departments.append(department)
    return departments


async def create_position(session: AsyncSession, payload: PositionUpsertRequest) -> Position:
    repository = PositionRepository(session)
    if await repository.get_by_code(payload.code):
        raise ConflictError("Position code already exists.")
    position = Position(
        title=payload.title,
        code=payload.code.upper(),
        is_active=payload.is_active,
    )
    created = await repository.create(position)
    if payload.department_ids:
        departments = await _resolve_departments(session, payload.department_ids)
        created.departments = departments
        created = await repository.save(created)
    hydrated = await repository.get_by_id(created.id)
    if hydrated is None:
        raise NotFoundError("Position not found.")
    return hydrated


async def update_position(
    session: AsyncSession, position_id: int, payload: PositionUpsertRequest
) -> Position:
    repository = PositionRepository(session)
    position = await repository.get_by_id(position_id)
    if position is None:
        raise NotFoundError("Position not found.")
    existing = await repository.get_by_code(payload.code)
    if existing is not None and existing.id != position_id:
        raise ConflictError("Position code already exists.")
    position.title = payload.title
    position.code = payload.code.upper()
    position.is_active = payload.is_active
    position.departments = await _resolve_departments(session, payload.department_ids)
    saved = await repository.save(position)
    hydrated = await repository.get_by_id(saved.id)
    if hydrated is None:
        raise NotFoundError("Position not found.")
    return hydrated


async def delete_position(session: AsyncSession, position_id: int) -> None:
    repository = PositionRepository(session)
    position = await repository.get_by_id(position_id)
    if position is None:
        raise NotFoundError("Position not found.")
    await repository.delete(position)


async def list_fixed_compensations(
    session: AsyncSession, month: int | None = None, year: int | None = None
) -> list[FixedCompensation]:
    return await FixedCompensationRepository(session).list(month=month, year=year)


async def create_fixed_compensation(
    session: AsyncSession, payload: FixedCompensationUpsertRequest
) -> FixedCompensation:
    repository = FixedCompensationRepository(session)
    compensation = FixedCompensation(
        name=payload.name.strip().title(),
        amount=payload.amount,
        month=payload.month,
        year=payload.year,
    )
    created = await repository.create(compensation)
    if payload.user_ids:
        created.users = await _resolve_users(session, payload.user_ids)
        created = await repository.save(created)
    return created


async def update_fixed_compensation(
    session: AsyncSession, compensation_id: int, payload: FixedCompensationUpsertRequest
) -> FixedCompensation:
    repository = FixedCompensationRepository(session)
    compensation = await repository.get_by_id(compensation_id)
    if compensation is None:
        raise NotFoundError("Fixed compensation not found.")
    compensation.name = payload.name.strip().title()
    compensation.amount = payload.amount
    compensation.month = payload.month
    compensation.year = payload.year
    compensation.users = await _resolve_users(session, payload.user_ids)
    return await repository.save(compensation)


async def delete_fixed_compensation(session: AsyncSession, compensation_id: int) -> None:
    repository = FixedCompensationRepository(session)
    compensation = await repository.get_by_id(compensation_id)
    if compensation is None:
        raise NotFoundError("Fixed compensation not found.")
    await repository.delete(compensation)


async def update_fixed_compensation_users(
    session: AsyncSession, compensation_id: int, payload: FixedCompensationUsersRequest
) -> FixedCompensation:
    repository = FixedCompensationRepository(session)
    compensation = await repository.get_by_id(compensation_id)
    if compensation is None:
        raise NotFoundError("Fixed compensation not found.")
    compensation.users = await _resolve_users(session, payload.user_ids)
    return await repository.save(compensation)


async def _resolve_users(session: AsyncSession, user_ids: list[UUID]) -> list[User]:
    user_repository = UserRepository(session)
    users: list[User] = []
    for user_id in user_ids:
        user = await user_repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        users.append(user)
    return users


async def get_payslips(
    session: AsyncSession,
    user_id: UUID | None = None,
    month: int | None = None,
    year: int | None = None,
    period: str | None = None,
    released: bool | None = None,
) -> list[Payslip]:
    return await PayslipRepository(session).list(
        user_id=user_id, month=month, year=year, period=period, released=released
    )


async def _current_salary_for_user(
    session: AsyncSession,
    user: User,
    *,
    month: int | None = None,
    year: int | None = None,
    period: str | None = None,
) -> Decimal | None:
    effective_date = resolve_mp2_effective_date(month, year, period)
    assignment = await UserSalaryAssignmentRepository(session).get_active_for_user_on(
        user.id,
        effective_date,
    )
    if assignment is not None:
        return _to_decimal(assignment.monthly_salary).quantize(Decimal("0.01"))
    if user.monthly_salary is None:
        return None
    return _to_decimal(user.monthly_salary).quantize(Decimal("0.01"))


async def _mp2_deduction_for_user(
    session: AsyncSession,
    user_id: UUID,
    effective_date: date,
) -> Decimal:
    enrollment = await get_active_mp2_for_user(session, user_id, effective_date)
    if enrollment is not None:
        return _to_decimal(enrollment.amount).quantize(Decimal("0.01"))
    return Decimal("0.00")


async def get_or_create_payslip(
    session: AsyncSession, payload: PayslipCreateRequest
) -> Payslip:
    user = await UserRepository(session).get_by_id(payload.user_id)
    if user is None:
        raise NotFoundError("User not found.")
    repository = PayslipRepository(session)
    payslip = await repository.get_by_identity(
        payload.user_id, payload.month, payload.year, payload.period
    )
    if payslip is None:
        settings = await get_settings(session)
        automatic_deduction_schedule = settings.automatic_deduction_schedule
        if payload.period == "2ND":
            existing_cutoffs = await repository.list(
                user_id=payload.user_id,
                month=payload.month,
                year=payload.year,
            )
            first_cutoff = next(
                (
                    item
                    for item in existing_cutoffs
                    if item.period == "1ST" and item.released
                ),
                None,
            )
            if (
                first_cutoff is not None
                and first_cutoff.automatic_deduction_schedule
            ):
                automatic_deduction_schedule = first_cutoff.automatic_deduction_schedule
        salary = await _current_salary_for_user(
            session,
            user,
            month=payload.month,
            year=payload.year,
            period=payload.period,
        )
        payslip = Payslip(
            user_id=payload.user_id,
            month=payload.month,
            year=payload.year,
            period=payload.period,
            salary=salary,
            automatic_deduction_schedule=automatic_deduction_schedule,
        )
        payslip = await repository.create(payslip)
    elif not payslip.released:
        salary = await _current_salary_for_user(
            session,
            user,
            month=payload.month,
            year=payload.year,
            period=payload.period,
        )
        payslip.salary = salary
        payslip = await repository.save(payslip)
    return payslip


async def update_payslip(
    session: AsyncSession, payslip_id: int, payload: PayslipUpdateRequest
) -> Payslip:
    repository = PayslipRepository(session)
    payslip = await repository.get_by_id(payslip_id)
    if payslip is None:
        raise NotFoundError("Payslip not found.")
    was_released = payslip.released
    if payload.salary is not None:
        payslip.salary = payload.salary
    if payload.released is not None:
        payslip.released = payload.released
        payslip.release_date = utc_now() if payload.released else None
    payslip = await repository.save(payslip)
    if not was_released and payslip.released:
        await create_notification_if_possible(
            session,
            recipient_id=payslip.user_id,
            content=(
                f"Your payslip for {payslip.month}/{payslip.year} "
                f"({payslip.period}) is now available."
            ),
            url=f"/my-payslips?payslip_id={payslip.id}",
        )
    return payslip


async def toggle_payslip_release(session: AsyncSession, payslip_id: int) -> Payslip:
    repository = PayslipRepository(session)
    payslip = await repository.get_by_id(payslip_id)
    if payslip is None:
        raise NotFoundError("Payslip not found.")
    payslip.released = not payslip.released
    payslip.release_date = utc_now() if payslip.released else None
    payslip = await repository.save(payslip)
    if payslip.released:
        await create_notification_if_possible(
            session,
            recipient_id=payslip.user_id,
            content=(
                f"Your payslip for {payslip.month}/{payslip.year} "
                f"({payslip.period}) is now available."
            ),
            url=f"/my-payslips?payslip_id={payslip.id}",
        )
    return payslip


async def delete_payslip(session: AsyncSession, payslip_id: int) -> None:
    repository = PayslipRepository(session)
    payslip = await repository.get_by_id(payslip_id)
    if payslip is None:
        raise NotFoundError("Payslip not found.")
    if payslip.released:
        raise ConflictError("Released payslip cannot be deleted.")
    await repository.delete(payslip)


def _get_config_item(settings: PayrollSetting, name: str) -> dict:
    for item in settings.deduction_config:
        if item.get("name") == name:
            return item
    return {"data": {}}


def _compute_deductions(settings: PayrollSetting, gross_pay: Decimal) -> dict[str, Decimal]:
    sss = _get_config_item(settings, "SSS").get("data", {})
    philhealth = _get_config_item(settings, "PHILHEALTH").get("data", {})
    pagibig = _get_config_item(settings, "PAG-IBIG").get("data", {})

    sss_deduction = Decimal(sss.get("min_contribution", "0"))
    philhealth_rate = _to_decimal(philhealth.get("rate"))
    philhealth_deduction = (gross_pay * philhealth_rate) / Decimal("200") if philhealth_rate else Decimal("0.00")
    tax_deduction = Decimal("0.00")
    pag_ibig_deduction = _to_decimal(pagibig.get("amount"))

    return {
        "sss": sss_deduction,
        "philhealth": philhealth_deduction.quantize(Decimal("0.01")),
        "tax": tax_deduction,
        "pag_ibig": pag_ibig_deduction.quantize(Decimal("0.01")),
    }


async def get_payslip_summary(session: AsyncSession, payslip_id: int) -> dict:
    repository = PayslipRepository(session)
    payslip = await repository.get_by_id(payslip_id)
    if payslip is None:
        raise NotFoundError("Payslip not found.")
    settings = await get_settings(session)
    fixed_compensations = await FixedCompensationRepository(session).list(
        month=payslip.month, year=payslip.year
    )
    base_salary = _to_decimal(payslip.salary)
    fixed_total = sum(
        (_to_decimal(comp.amount) / Decimal("2") for comp in fixed_compensations if payslip.user in comp.users),
        Decimal("0.00"),
    )
    variable_compensations = payslip.variable_compensations
    variable_deductions = payslip.variable_deductions
    variable_comp_total = sum((_to_decimal(item.amount) for item in variable_compensations), Decimal("0.00"))
    variable_ded_total = sum((_to_decimal(item.amount) for item in variable_deductions), Decimal("0.00"))
    gross_pay = base_salary + fixed_total + variable_comp_total
    gross_per_cutoff = _semi_monthly_base_from_monthly(base_salary) + variable_comp_total
    mandatory = _compute_deductions(settings, gross_pay)
    mandatory_total = sum(mandatory.values(), Decimal("0.00"))
    effective_date = resolve_mp2_effective_date(payslip.month, payslip.year, payslip.period)
    mp2_deduction = await _mp2_deduction_for_user(session, payslip.user.id, effective_date)
    total_deductions = variable_ded_total
    if payslip.period == "2ND":
        total_deductions += mandatory_total + mp2_deduction
    return {
        "period": payslip.period,
        "salary": base_salary / Decimal("2") if base_salary else None,
        "compensations": fixed_compensations,
        "variable_compensations": variable_compensations,
        "gross_pay": gross_per_cutoff.quantize(Decimal("0.01")),
        "variable_deductions": variable_deductions,
        "total_deductions": total_deductions.quantize(Decimal("0.01")),
        "net_salary": (gross_per_cutoff - total_deductions).quantize(Decimal("0.01")),
        "sss_deduction": mandatory["sss"],
        "philhealth_deduction": mandatory["philhealth"],
        "pag_ibig_deduction": mandatory["pag_ibig"],
        "mp2_deduction": mp2_deduction,
        "tax_deduction": mandatory["tax"],
    }


async def add_payslip_variable_compensation(
    session: AsyncSession,
    payslip_id: int,
    payload: PayslipVariableCompensationUpsertRequest,
) -> PayslipVariableCompensation:
    repository = PayslipVariableCompensationRepository(session)
    payslip = await PayslipRepository(session).get_by_id(payslip_id)
    if payslip is None:
        raise NotFoundError("Payslip not found.")
    item = PayslipVariableCompensation(
        payslip_id=payslip_id, name=payload.name.strip(), amount=payload.amount
    )
    return await repository.create(item)


async def remove_payslip_variable_compensation(
    session: AsyncSession, item_id: int
) -> None:
    repository = PayslipVariableCompensationRepository(session)
    item = await repository.get_by_id(item_id)
    if item is None:
        raise NotFoundError("Variable compensation not found.")
    await repository.delete(item)


async def add_payslip_variable_deduction(
    session: AsyncSession,
    payslip_id: int,
    payload: PayslipVariableDeductionUpsertRequest,
) -> PayslipVariableDeduction:
    repository = PayslipVariableDeductionRepository(session)
    payslip = await PayslipRepository(session).get_by_id(payslip_id)
    if payslip is None:
        raise NotFoundError("Payslip not found.")
    item = PayslipVariableDeduction(
        payslip_id=payslip_id, name=payload.name.strip(), amount=payload.amount
    )
    return await repository.create(item)


async def remove_payslip_variable_deduction(
    session: AsyncSession, item_id: int
) -> None:
    repository = PayslipVariableDeductionRepository(session)
    item = await repository.get_by_id(item_id)
    if item is None:
        raise NotFoundError("Variable deduction not found.")
    await repository.delete(item)


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _compute_payout_totals(
    gross_amount: Decimal, adjustments: list[ThirteenthMonthAdjustment]
) -> tuple[Decimal, Decimal]:
    additions = sum(
        (_to_decimal(item.amount) for item in adjustments if item.type == "ADD"),
        Decimal("0.00"),
    )
    deductions = sum(
        (_to_decimal(item.amount) for item in adjustments if item.type == "DEDUCT"),
        Decimal("0.00"),
    )
    net = gross_amount + additions - deductions
    return _round_money(deductions), _round_money(net)


def _preferred_payslip(current: Payslip | None, candidate: Payslip) -> Payslip:
    if current is None:
        return candidate
    if candidate.period == "2ND" and current.period != "2ND":
        return candidate
    if candidate.period == current.period and candidate.id > current.id:
        return candidate
    return current


async def list_thirteenth_month_payouts(
    session: AsyncSession,
    year: int | None = None,
    user_id: UUID | None = None,
    status: str | None = None,
) -> list[ThirteenthMonthPayout]:
    return await ThirteenthMonthPayoutRepository(session).list(
        user_id=user_id,
        year=year,
        status=status,
    )


async def list_my_thirteenth_month_payouts(
    session: AsyncSession, user_id: UUID, year: int | None = None
) -> list[ThirteenthMonthPayout]:
    return await ThirteenthMonthPayoutRepository(session).list(
        user_id=user_id,
        year=year,
        status="RELEASED",
    )


async def generate_thirteenth_month_payouts(
    session: AsyncSession, payload: ThirteenthMonthGenerateRequest
) -> list[ThirteenthMonthPayout]:
    payout_repository = ThirteenthMonthPayoutRepository(session)
    adjustment_repository = ThirteenthMonthAdjustmentRepository(session)
    users = await UserRepository(session).list(include_superusers=False)
    # 13th month uses earned basic salary for the calendar year, not release state.
    payslips = await PayslipRepository(session).list(year=payload.year)

    selected_monthly_payslips: dict[tuple[UUID, int], Payslip] = {}
    for payslip in payslips:
        if payslip.month is None:
            continue
        key = (payslip.user_id, payslip.month)
        selected_monthly_payslips[key] = _preferred_payslip(
            selected_monthly_payslips.get(key), payslip
        )

    annual_basic_salary_by_user: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for payslip in selected_monthly_payslips.values():
        annual_basic_salary_by_user[payslip.user_id] += _to_decimal(payslip.salary)

    generated_ids: list[int] = []
    for user in users:
        gross_amount = _round_money(annual_basic_salary_by_user[user.id] / Decimal("12"))
        payout = await payout_repository.get_by_user_year(user.id, payload.year)

        if payout is None:
            payout = await payout_repository.create(
                ThirteenthMonthPayout(
                    user_id=user.id,
                    year=payload.year,
                    gross_amount=gross_amount,
                    total_deductions=Decimal("0.00"),
                    net_amount=gross_amount,
                    status="DRAFT",
                )
            )
            generated_ids.append(payout.id)
            continue

        if payout.status == "RELEASED":
            generated_ids.append(payout.id)
            continue

        adjustments = await adjustment_repository.list_by_payout_id(payout.id)
        payout.gross_amount = gross_amount
        payout.total_deductions, payout.net_amount = _compute_payout_totals(
            gross_amount, adjustments
        )
        saved = await payout_repository.save(payout)
        generated_ids.append(saved.id)

    payouts: list[ThirteenthMonthPayout] = []
    for payout_id in generated_ids:
        payout = await payout_repository.get_by_id(payout_id)
        if payout is not None:
            payouts.append(payout)
    return payouts


async def add_thirteenth_month_adjustment(
    session: AsyncSession,
    payout_id: int,
    payload: ThirteenthMonthAdjustmentCreateRequest,
) -> ThirteenthMonthPayout:
    payout_repository = ThirteenthMonthPayoutRepository(session)
    adjustment_repository = ThirteenthMonthAdjustmentRepository(session)

    payout = await payout_repository.get_by_id(payout_id)
    if payout is None:
        raise NotFoundError("13th month payout not found.")
    if payout.status == "RELEASED":
        raise ConflictError("Released 13th month payout cannot be modified.")

    item = ThirteenthMonthAdjustment(
        payout_id=payout_id,
        type=payload.type,
        label=payload.label.strip(),
        amount=payload.amount,
        reason=_normalize_optional_text(payload.reason),
    )
    await adjustment_repository.create(item)

    adjustments = await adjustment_repository.list_by_payout_id(payout_id)
    payout.total_deductions, payout.net_amount = _compute_payout_totals(
        _to_decimal(payout.gross_amount), adjustments
    )
    saved = await payout_repository.save(payout)
    loaded = await payout_repository.get_by_id(saved.id)
    return loaded if loaded is not None else saved


async def remove_thirteenth_month_adjustment(
    session: AsyncSession, adjustment_id: int
) -> ThirteenthMonthPayout:
    payout_repository = ThirteenthMonthPayoutRepository(session)
    adjustment_repository = ThirteenthMonthAdjustmentRepository(session)

    item = await adjustment_repository.get_by_id(adjustment_id)
    if item is None:
        raise NotFoundError("13th month adjustment not found.")

    payout = await payout_repository.get_by_id(item.payout_id)
    if payout is None:
        raise NotFoundError("13th month payout not found.")
    if payout.status == "RELEASED":
        raise ConflictError("Released 13th month payout cannot be modified.")

    await adjustment_repository.delete(item)
    adjustments = await adjustment_repository.list_by_payout_id(payout.id)
    payout.total_deductions, payout.net_amount = _compute_payout_totals(
        _to_decimal(payout.gross_amount), adjustments
    )
    saved = await payout_repository.save(payout)
    loaded = await payout_repository.get_by_id(saved.id)
    return loaded if loaded is not None else saved


async def release_thirteenth_month_payout(
    session: AsyncSession, payout_id: int
) -> ThirteenthMonthPayout:
    payout_repository = ThirteenthMonthPayoutRepository(session)

    payout = await payout_repository.get_by_id(payout_id)
    if payout is None:
        raise NotFoundError("13th month payout not found.")
    if payout.status == "RELEASED":
        return payout

    payout.status = "RELEASED"
    payout.released_at = utc_now()
    payout = await payout_repository.save(payout)

    await create_notification_if_possible(
        session,
        recipient_id=payout.user_id,
        content=f"Your 13th month payout for {payout.year} is now available.",
        url=f"/my-thirteenth-month?payout_id={payout.id}",
    )
    return payout
