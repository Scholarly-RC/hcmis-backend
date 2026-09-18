import anyio
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.models.department import Department
from app.models.payroll import (
    FixedCompensation,
    Mp2Enrollment,
    PayrollSetting,
    Payslip,
    Position,
    ThirteenthMonthAdjustment,
    ThirteenthMonthPayout,
)
from app.models.user import User, UserSalaryAssignment
from app.schemas.payroll import (
    Mp2EnrollmentCreateRequest,
    PositionUpsertRequest,
    PayrollSettingUpdateRequest,
    PayslipCreateRequest,
    PayslipVariableCompensationUpsertRequest,
    PayslipVariableDeductionUpsertRequest,
    ThirteenthMonthAdjustmentCreateRequest,
    ThirteenthMonthGenerateRequest,
)
from app.services import payroll_engine
from app.services import payroll as payroll_service


class FakeDepartmentRepository:
    departments: dict[int, Department] = {}

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, department_id: int):
        return self.departments.get(department_id)


class FakeUserRepository:
    users: dict[UUID, User] = {}

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, user_id: UUID):
        return self.users.get(user_id)

    async def list(self, include_superusers: bool = False, **kwargs):
        return list(self.users.values())


class FakePayrollSettingRepository:
    setting: PayrollSetting | None = None

    def __init__(self, session):
        self.session = session

    async def get_first(self):
        return self.setting

    async def create(self, settings: PayrollSetting):
        self.setting = settings
        return settings

    async def save(self, settings: PayrollSetting):
        self.setting = settings
        return settings

class FakeMp2EnrollmentRepository:
    items: dict[int, Mp2Enrollment] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, status=None):
        items = list(self.items.values())
        if status is not None:
            items = [item for item in items if item.status == status]
        return items

    async def get_by_id(self, enrollment_id: int):
        return self.items.get(enrollment_id)

    async def get_active_for_user_on(self, user_id: UUID, effective_date):
        candidates = [
            item
            for item in self.items.values()
            if item.user_id == user_id
            and item.status == "active"
            and item.effective_from <= effective_date
            and (item.effective_to is None or item.effective_to >= effective_date)
        ]
        candidates.sort(key=lambda item: (item.effective_from, item.id), reverse=True)
        return candidates[0] if candidates else None

    async def create(self, enrollment: Mp2Enrollment):
        enrollment.id = self.next_id
        self.next_id += 1
        enrollment.user = FakeUserRepository.users.get(enrollment.user_id)
        self.items[enrollment.id] = enrollment
        return enrollment

    async def save(self, enrollment: Mp2Enrollment):
        enrollment.user = FakeUserRepository.users.get(enrollment.user_id)
        self.items[enrollment.id] = enrollment
        return enrollment


class FakePositionRepository:
    positions: dict[int, Position] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, department_id=None):
        positions = list(self.positions.values())
        if department_id is not None:
            positions = [
                position
                for position in positions
                if any(dep.id == department_id for dep in position.departments)
            ]
        return positions

    async def get_by_id(self, position_id: int):
        return self.positions.get(position_id)

    async def get_by_code(self, code: str):
        for position in self.positions.values():
            if position.code.lower() == code.lower():
                return position
        return None

    async def create(self, position: Position):
        position.id = self.next_id
        self.next_id += 1
        self.positions[position.id] = position
        return position

    async def save(self, position: Position):
        self.positions[position.id] = position
        return position

    async def delete(self, position: Position):
        self.positions.pop(position.id, None)


class FakeFixedCompensationRepository:
    items: dict[int, FixedCompensation] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, month=None, year=None):
        items = list(self.items.values())
        if month is not None:
            items = [item for item in items if item.month == month]
        if year is not None:
            items = [item for item in items if item.year == year]
        return items

    async def get_by_id(self, compensation_id: int):
        return self.items.get(compensation_id)

    async def create(self, compensation: FixedCompensation):
        compensation.id = self.next_id
        self.next_id += 1
        self.items[compensation.id] = compensation
        return compensation

    async def save(self, compensation: FixedCompensation):
        self.items[compensation.id] = compensation
        return compensation

    async def delete(self, compensation: FixedCompensation):
        self.items.pop(compensation.id, None)


class FakePayslipRepository:
    items: dict[int, Payslip] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, user_id=None, month=None, year=None, period=None, released=None):
        items = list(self.items.values())
        if user_id is not None:
            items = [item for item in items if item.user_id == user_id]
        if month is not None:
            items = [item for item in items if item.month == month]
        if year is not None:
            items = [item for item in items if item.year == year]
        if period is not None:
            items = [item for item in items if item.period == period]
        if released is not None:
            items = [item for item in items if item.released == released]
        return items

    async def get_by_id(self, payslip_id: int):
        return self.items.get(payslip_id)

    async def get_by_identity(self, user_id: UUID, month: int, year: int, period: str):
        for item in self.items.values():
            if (
                item.user_id == user_id
                and item.month == month
                and item.year == year
                and item.period == period
            ):
                return item
        return None

    async def create(self, payslip: Payslip):
        payslip.id = self.next_id
        self.next_id += 1
        payslip.created_at = payslip.created_at or utc_now()
        payslip.updated_at = payslip.updated_at or utc_now()
        payslip.user = FakeUserRepository.users.get(payslip.user_id)
        self.items[payslip.id] = payslip
        return payslip

    async def save(self, payslip: Payslip):
        payslip.updated_at = utc_now()
        payslip.user = FakeUserRepository.users.get(payslip.user_id)
        self.items[payslip.id] = payslip
        return payslip

    async def delete(self, payslip: Payslip):
        self.items.pop(payslip.id, None)


class FakePayslipVariableCompensationRepository:
    items: dict[int, object] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def create(self, item):
        item.id = self.next_id
        self.next_id += 1
        self.items[item.id] = item
        return item

    async def get_by_id(self, item_id: int):
        return self.items.get(item_id)

    async def delete(self, item):
        self.items.pop(item.id, None)


class FakePayslipVariableDeductionRepository(FakePayslipVariableCompensationRepository):
    pass


class FakeUserSalaryAssignmentRepository:
    items: dict[int, UserSalaryAssignment] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def get_active_for_user_on(self, user_id: UUID, effective_date):
        candidates = [
            item
            for item in self.items.values()
            if item.user_id == user_id
            and item.effective_from <= effective_date
            and (item.effective_to is None or item.effective_to >= effective_date)
        ]
        candidates.sort(key=lambda item: (item.effective_from, item.id), reverse=True)
        return candidates[0] if candidates else None


class FakeThirteenthMonthPayoutRepository:
    items: dict[int, ThirteenthMonthPayout] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, user_id=None, year=None, status=None):
        items = list(self.items.values())
        if user_id is not None:
            items = [item for item in items if item.user_id == user_id]
        if year is not None:
            items = [item for item in items if item.year == year]
        if status is not None:
            items = [item for item in items if item.status == status]
        return items

    async def get_by_id(self, item_id: int):
        return self.items.get(item_id)

    async def get_by_user_year(self, user_id: UUID, year: int):
        for item in self.items.values():
            if item.user_id == user_id and item.year == year:
                return item
        return None

    async def create(self, item: ThirteenthMonthPayout):
        item.id = self.next_id
        self.next_id += 1
        self.items[item.id] = item
        return item

    async def save(self, item: ThirteenthMonthPayout):
        self.items[item.id] = item
        return item

    async def delete(self, item: ThirteenthMonthPayout):
        self.items.pop(item.id, None)


class FakeThirteenthMonthAdjustmentRepository:
    items: dict[int, ThirteenthMonthAdjustment] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def create(self, item):
        item.id = self.next_id
        self.next_id += 1
        self.items[item.id] = item
        return item

    async def get_by_id(self, item_id: int):
        return self.items.get(item_id)

    async def list_by_payout_id(self, payout_id: int):
        return [item for item in self.items.values() if item.payout_id == payout_id]

    async def delete(self, item):
        self.items.pop(item.id, None)


def _reset():
    FakePayrollSettingRepository.setting = None
    FakeMp2EnrollmentRepository.items = {}
    FakeMp2EnrollmentRepository.next_id = 1
    FakePositionRepository.positions = {}
    FakePositionRepository.next_id = 1
    FakeFixedCompensationRepository.items = {}
    FakeFixedCompensationRepository.next_id = 1
    FakePayslipRepository.items = {}
    FakePayslipRepository.next_id = 1
    FakePayslipVariableCompensationRepository.items = {}
    FakePayslipVariableCompensationRepository.next_id = 1
    FakePayslipVariableDeductionRepository.items = {}
    FakePayslipVariableDeductionRepository.next_id = 1
    FakeUserSalaryAssignmentRepository.items = {}
    FakeUserSalaryAssignmentRepository.next_id = 1
    FakeThirteenthMonthPayoutRepository.items = {}
    FakeThirteenthMonthPayoutRepository.next_id = 1
    FakeThirteenthMonthAdjustmentRepository.items = {}
    FakeThirteenthMonthAdjustmentRepository.next_id = 1
    FakeUserRepository.users = {}
    FakeDepartmentRepository.departments = {}


def _seed():
    dept = Department(id=1, name="Operations", code="OPS", is_active=True, workweek=[])
    FakeDepartmentRepository.departments[1] = dept
    position = Position(id=1, title="Operations Staff", code="OPS", is_active=True)
    position.departments = [dept]
    FakePositionRepository.positions[1] = position
    user = User(
        id=UUID(int=1),
        email="employee@example.com",
        password_hash="hashed",
        first_name="Employee",
        last_name="One",
        position_id=1,
        monthly_salary=Decimal("1000.00"),
        department_id=1,
        can_modify_shift=False,
        is_active=True,
        is_superuser=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    user.department = dept
    FakeUserRepository.users[UUID(int=1)] = user

    FakePayrollSettingRepository.setting = PayrollSetting(
        id=1,
        deduction_config=payroll_service.DEFAULT_DEDUCTION_CONFIG,
        automatic_deduction_schedule="SECOND_CUTOFF_ONLY",
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_payroll_settings_and_positions(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(payroll_service, "DepartmentRepository", FakeDepartmentRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )

    settings = anyio.run(payroll_service.get_settings, cast(AsyncSession, object()))
    assert settings.automatic_deduction_schedule == "SECOND_CUTOFF_ONLY"

    updated = anyio.run(
        payroll_service.update_settings,
        cast(AsyncSession, object()),
        PayrollSettingUpdateRequest(automatic_deduction_schedule="SPLIT_BOTH_CUTOFFS"),
    )
    assert updated.automatic_deduction_schedule == "SPLIT_BOTH_CUTOFFS"

    position = anyio.run(
        payroll_service.create_position,
        cast(AsyncSession, object()),
        PositionUpsertRequest(title="Staff", code="STAFF", department_ids=[1]),
    )
    assert position.code == "STAFF"


def test_position_request_normalizes_and_validates_code():
    payload = PositionUpsertRequest(
        title="  Staff  ",
        code=" ops1 ",
        department_ids=[1],
    )
    assert payload.title == "Staff"
    assert payload.code == "OPS1"

    try:
        PositionUpsertRequest(
            title="Staff",
            code="OPS-1",
        )
        raise AssertionError("Expected validation error for invalid position code.")
    except ValidationError:
        pass


def test_payslip_calculation_and_variable_adjustments(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "Mp2EnrollmentRepository", FakeMp2EnrollmentRepository)
    monkeypatch.setattr(payroll_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(payroll_service, "DepartmentRepository", FakeDepartmentRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )
    monkeypatch.setattr(payroll_service, "FixedCompensationRepository", FakeFixedCompensationRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(payroll_service, "PayslipVariableCompensationRepository", FakePayslipVariableCompensationRepository)
    monkeypatch.setattr(payroll_service, "PayslipVariableDeductionRepository", FakePayslipVariableDeductionRepository)

    fixed = FixedCompensation(
        id=1,
        name="Rice Allowance",
        amount=Decimal("200.00"),
        month=1,
        year=2026,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    fixed.users = [FakeUserRepository.users[UUID(int=1)]]
    FakeFixedCompensationRepository.items[1] = fixed

    payslip = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="2ND"),
    )
    assert payslip.salary == Decimal("1000.00")

    comp = anyio.run(
        payroll_service.add_payslip_variable_compensation,
        cast(AsyncSession, object()),
        payslip.id,
        PayslipVariableCompensationUpsertRequest(name="Bonus", amount=Decimal("100.00")),
    )
    assert comp.name == "Bonus"

    ded = anyio.run(
        payroll_service.add_payslip_variable_deduction,
        cast(AsyncSession, object()),
        payslip.id,
        PayslipVariableDeductionUpsertRequest(name="Loan", amount=Decimal("50.00")),
    )
    assert ded.name == "Loan"

    summary = anyio.run(
        payroll_service.get_payslip_summary,
        cast(AsyncSession, object()),
        payslip.id,
    )
    assert summary["net_salary"] is not None


def test_payslip_salary_is_none_when_employee_salary_is_unconfigured(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)

    user = FakeUserRepository.users[UUID(int=1)]
    user.monthly_salary = None

    payslip = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="2ND"),
    )
    assert payslip.salary is None


def test_payslip_uses_effective_salary_assignment_before_user_salary(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )

    user = FakeUserRepository.users[UUID(int=1)]
    FakeUserSalaryAssignmentRepository.items[1] = UserSalaryAssignment(
        id=1,
        user_id=user.id,
        monthly_salary=Decimal("1250.00"),
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )

    payslip = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="2ND"),
    )
    assert payslip.salary == Decimal("1250.00")


def test_mp2_enrollment_and_summary_deduction(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "Mp2EnrollmentRepository", FakeMp2EnrollmentRepository)
    monkeypatch.setattr(payroll_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(payroll_service, "DepartmentRepository", FakeDepartmentRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )
    monkeypatch.setattr(payroll_service, "FixedCompensationRepository", FakeFixedCompensationRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(payroll_service, "PayslipVariableCompensationRepository", FakePayslipVariableCompensationRepository)
    monkeypatch.setattr(payroll_service, "PayslipVariableDeductionRepository", FakePayslipVariableDeductionRepository)

    async def _create_mp2_enrollment():
        return await payroll_service.create_mp2_enrollment(
            cast(AsyncSession, object()),
            Mp2EnrollmentCreateRequest(
                user_id=UUID(int=1),
                amount=Decimal("123.45"),
                effective_from=date(2026, 1, 1),
            ),
        )

    mp2_enrollment = anyio.run(_create_mp2_enrollment)
    assert mp2_enrollment.amount == Decimal("123.45")
    assert mp2_enrollment.user_id == UUID(int=1)

    fixed = FixedCompensation(
        id=1,
        name="Rice Allowance",
        amount=Decimal("200.00"),
        month=1,
        year=2026,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    fixed.users = [FakeUserRepository.users[UUID(int=1)]]
    FakeFixedCompensationRepository.items[1] = fixed

    payslip = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="2ND"),
    )
    summary = anyio.run(
        payroll_service.get_payslip_summary,
        cast(AsyncSession, object()),
        payslip.id,
    )
    assert summary["mp2_deduction"] == Decimal("123.45")
    assert summary["total_deductions"] == Decimal("123.45")


def test_automatic_deductions_default_to_second_cutoff_only():
    mandatory, mp2, notes = payroll_engine._resolve_automatic_deductions(
        {
            "sss": Decimal("100.00"),
            "philhealth": Decimal("80.00"),
            "pag_ibig": Decimal("50.00"),
            "tax": Decimal("200.00"),
        },
        Decimal("300.00"),
        "SECOND_CUTOFF_ONLY",
        "1ST",
    )

    assert mandatory == {
        "sss": Decimal("0.00"),
        "philhealth": Decimal("0.00"),
        "pag_ibig": Decimal("0.00"),
        "tax": Decimal("0.00"),
    }
    assert mp2 == Decimal("0.00")
    assert notes == ["MP2 deduction skipped for non-second cutoff period."]


def test_automatic_deductions_can_split_across_both_cutoffs():
    first_mandatory, first_mp2, first_notes = payroll_engine._resolve_automatic_deductions(
        {
            "sss": Decimal("101.00"),
            "philhealth": Decimal("80.00"),
            "pag_ibig": Decimal("50.00"),
            "tax": Decimal("200.00"),
        },
        Decimal("301.00"),
        "SPLIT_BOTH_CUTOFFS",
        "1ST",
    )
    second_mandatory, second_mp2, second_notes = payroll_engine._resolve_automatic_deductions(
        {
            "sss": Decimal("101.00"),
            "philhealth": Decimal("80.00"),
            "pag_ibig": Decimal("50.00"),
            "tax": Decimal("200.00"),
        },
        Decimal("301.00"),
        "SPLIT_BOTH_CUTOFFS",
        "2ND",
    )

    assert first_mandatory == {
        "sss": Decimal("50.50"),
        "philhealth": Decimal("40.00"),
        "pag_ibig": Decimal("25.00"),
        "tax": Decimal("100.00"),
    }
    assert second_mandatory == first_mandatory
    assert first_mp2 == Decimal("150.50")
    assert second_mp2 == Decimal("150.50")
    assert first_notes == []
    assert second_notes == []


def test_new_payslip_snapshots_deduction_schedule(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )

    settings = FakePayrollSettingRepository.setting
    assert settings is not None
    settings.automatic_deduction_schedule = "SPLIT_BOTH_CUTOFFS"

    payslip = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="1ST"),
    )

    assert payslip.automatic_deduction_schedule == "SPLIT_BOTH_CUTOFFS"


def test_existing_payslip_keeps_snapshotted_deduction_schedule(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )

    settings = FakePayrollSettingRepository.setting
    assert settings is not None
    settings.automatic_deduction_schedule = "SECOND_CUTOFF_ONLY"

    payslip = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="1ST"),
    )
    assert payslip.automatic_deduction_schedule == "SECOND_CUTOFF_ONLY"

    settings.automatic_deduction_schedule = "SPLIT_BOTH_CUTOFFS"

    refreshed = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="1ST"),
    )
    assert refreshed.id == payslip.id
    assert refreshed.automatic_deduction_schedule == "SECOND_CUTOFF_ONLY"


def test_second_cutoff_inherits_month_schedule_from_released_first_cutoff(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )

    settings = FakePayrollSettingRepository.setting
    assert settings is not None
    settings.automatic_deduction_schedule = "SPLIT_BOTH_CUTOFFS"

    first_cutoff = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="1ST"),
    )
    first_cutoff.released = True
    assert first_cutoff.automatic_deduction_schedule == "SPLIT_BOTH_CUTOFFS"

    settings.automatic_deduction_schedule = "SECOND_CUTOFF_ONLY"

    second_cutoff = anyio.run(
        payroll_service.get_or_create_payslip,
        cast(AsyncSession, object()),
        PayslipCreateRequest(user_id=UUID(int=1), month=1, year=2026, period="2ND"),
    )

    assert second_cutoff.automatic_deduction_schedule == "SPLIT_BOTH_CUTOFFS"


def test_thirteenth_month_payout_flow(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(payroll_service, "PayrollSettingRepository", FakePayrollSettingRepository)
    monkeypatch.setattr(payroll_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(payroll_service, "DepartmentRepository", FakeDepartmentRepository)
    monkeypatch.setattr(payroll_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(payroll_service, "PayslipRepository", FakePayslipRepository)
    monkeypatch.setattr(
        payroll_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )
    monkeypatch.setattr(payroll_service, "ThirteenthMonthPayoutRepository", FakeThirteenthMonthPayoutRepository)
    monkeypatch.setattr(payroll_service, "ThirteenthMonthAdjustmentRepository", FakeThirteenthMonthAdjustmentRepository)

    payslip_repository = FakePayslipRepository(cast(AsyncSession, object()))
    for month in range(1, 13):
        payslip = Payslip(
            user_id=UUID(int=1),
            month=month,
            year=2026,
            period="2ND",
            salary=Decimal("12000.00"),
            released=month % 2 == 0,
        )
        anyio.run(payslip_repository.create, payslip)

    generated = anyio.run(
        payroll_service.generate_thirteenth_month_payouts,
        cast(AsyncSession, object()),
        ThirteenthMonthGenerateRequest(year=2026),
    )
    assert len(generated) == 1
    payout = generated[0]
    assert payout.gross_amount == Decimal("12000.00")
    assert payout.net_amount == Decimal("12000.00")

    adjusted = anyio.run(
        payroll_service.add_thirteenth_month_adjustment,
        cast(AsyncSession, object()),
        payout.id,
        ThirteenthMonthAdjustmentCreateRequest(
            type="DEDUCT",
            label="Gov Loan",
            amount=Decimal("500.00"),
            reason="Loan offset",
        ),
    )
    assert adjusted.total_deductions == Decimal("500.00")
    assert adjusted.net_amount == Decimal("11500.00")

    released = anyio.run(
        payroll_service.release_thirteenth_month_payout,
        cast(AsyncSession, object()),
        payout.id,
    )
    assert released.status == "RELEASED"
    assert released.released_at is not None
