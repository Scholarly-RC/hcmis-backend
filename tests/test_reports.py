import anyio
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.models.attendance import DailyShiftRecord, DailyShiftSchedule, Shift
from app.models.department import Department
from app.models.leave import LeaveRequest, LeaveType
from app.models.performance import Evaluation, Questionnaire, UserEvaluation
from app.models.payroll import Payslip
from app.models.user import User
from app.services import reports as reports_service


class FakeReportsRepository:
    users: dict[UUID, User] = {}
    departments: dict[int, Department] = {}
    daily_shift_records: list[DailyShiftRecord] = []
    leave_requests: list[LeaveRequest] = []
    payslips: list[Payslip] = []
    user_evaluations: list[UserEvaluation] = []

    def __init__(self, session):
        self.session = session

    async def get_user(self, user_id: UUID):
        return self.users.get(user_id)

    async def list_users(self, as_of_date=None, active_only=True, include_superusers=False):
        items = list(self.users.values())
        if active_only:
            items = [item for item in items if item.is_active]
        if not include_superusers:
            items = [item for item in items if not item.is_superuser]
        if as_of_date is not None:
            items = [
                item
                for item in items
                if item.date_of_hiring is None or item.date_of_hiring <= as_of_date
            ]
        return sorted(items, key=lambda user: (user.first_name, user.last_name))

    async def list_departments(self):
        return sorted(self.departments.values(), key=lambda department: department.name)

    async def list_daily_shift_records(self, selected_date):
        return [record for record in self.daily_shift_records if record.date == selected_date]

    async def list_leave_requests(self, user_id=None, from_date=None, to_date=None):
        items = list(self.leave_requests)
        if user_id is not None:
            items = [item for item in items if item.user_id == user_id]
        if from_date is not None:
            items = [item for item in items if item.leave_date >= from_date]
        if to_date is not None:
            items = [item for item in items if item.leave_date <= to_date]
        return sorted(items, key=lambda item: item.leave_date)

    async def list_payslips(self, user_id=None, year=None, released=True):
        items = list(self.payslips)
        if user_id is not None:
            items = [item for item in items if item.user_id == user_id]
        if year is not None:
            items = [item for item in items if item.year == year]
        if released is not None:
            items = [item for item in items if item.released is released]
        return sorted(items, key=lambda item: (item.month or 0, item.period or ""))

    async def list_user_evaluations(self, user_id=None, year=None, finalized=True):
        items = list(self.user_evaluations)
        if user_id is not None:
            items = [item for item in items if item.evaluatee_id == user_id]
        if year is not None:
            items = [item for item in items if item.year == year]
        if finalized is not None:
            items = [item for item in items if item.is_finalized is finalized]
        return sorted(items, key=lambda item: (item.year, item.quarter))


def _reset():
    FakeReportsRepository.users = {}
    FakeReportsRepository.departments = {}
    FakeReportsRepository.daily_shift_records = []
    FakeReportsRepository.leave_requests = []
    FakeReportsRepository.payslips = []
    FakeReportsRepository.user_evaluations = []


def _seed():
    ops = Department(id=1, name="Operations", code="OPS", workweek=[], is_active=True)
    hr = User(
        id=UUID(int=1),
        email="hr@example.com",
        password_hash="hashed",
        first_name="Harriet",
        last_name="Resource",
        role="HR",
        department_id=1,
        date_of_hiring=date(2020, 1, 1),
        date_of_birth=date(1990, 1, 1),
        gender="F",
        highest_education_level="BA",
        highest_education_program="Bachelor of Science in Computer Science",
        religion="RC",
        is_active=True,
        is_superuser=False,
        can_modify_shift=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    hr.department = ops
    employee = User(
        id=UUID(int=2),
        email="employee@example.com",
        password_hash="hashed",
        first_name="Eddie",
        last_name="Worker",
        role="EMP",
        department_id=1,
        date_of_hiring=date(2023, 1, 1),
        date_of_birth=date(1995, 1, 1),
        gender="M",
        highest_education_level="HS",
        highest_education_program="",
        religion="IS",
        resignation_date=date(2026, 1, 15),
        is_active=False,
        is_superuser=False,
        can_modify_shift=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    employee.department = ops
    FakeReportsRepository.departments[1] = ops
    FakeReportsRepository.users[hr.id] = hr
    FakeReportsRepository.users[employee.id] = employee

    shift = Shift(
        id=1,
        description="Day shift",
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    schedule = DailyShiftSchedule(
        id=1,
        date=date(2026, 3, 24),
        user_id=employee.id,
        shift_id=1,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    schedule.user = employee
    schedule.shift = shift
    record = DailyShiftRecord(
        id=1,
        date=date(2026, 3, 24),
        department_id=1,
        is_approved=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    record.department = ops
    record.schedules = [schedule]
    FakeReportsRepository.daily_shift_records = [record]

    leave = LeaveRequest(
        id=1,
        user_id=employee.id,
        leave_date=date(2026, 3, 1),
        leave_type=LeaveType.PAID.value,
        info="Vacation",
        first_approver_status="APPROVED",
        second_approver_status="APPROVED",
        status="APPROVED",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    leave.user = employee
    FakeReportsRepository.leave_requests = [leave]

    payslip = Payslip(
        id=1,
        user_id=employee.id,
        salary=Decimal("1000.00"),
        period="2ND",
        released=True,
        month=3,
        year=2026,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    payslip.user = employee
    FakeReportsRepository.payslips = [payslip]

    questionnaire = Questionnaire(
        id=1,
        code="PE-2026",
        title="Performance 2026",
        content={"questionnaire_content": []},
        is_active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    user_evaluation = UserEvaluation(
        id=1,
        evaluatee_id=employee.id,
        questionnaire_id=1,
        quarter="FQ",
        year=2026,
        is_finalized=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    user_evaluation.evaluatee = employee
    user_evaluation.questionnaire = questionnaire
    self_eval = Evaluation(
        id=1,
        evaluator_id=employee.id,
        user_evaluation_id=1,
        questionnaire_id=1,
        content_data=[{"questions": [{"rating": 4}, {"rating": 4}]}],
        date_submitted=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    peer_eval = Evaluation(
        id=2,
        evaluator_id=hr.id,
        user_evaluation_id=1,
        questionnaire_id=1,
        content_data=[{"questions": [{"rating": 2}, {"rating": 4}]}],
        date_submitted=utc_now(),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    self_eval.evaluator = employee
    self_eval.user_evaluation = user_evaluation
    self_eval.questionnaire = questionnaire
    peer_eval.evaluator = hr
    peer_eval.user_evaluation = user_evaluation
    peer_eval.questionnaire = questionnaire
    user_evaluation.evaluations = [self_eval, peer_eval]
    FakeReportsRepository.user_evaluations = [user_evaluation]


def test_reports_catalog_and_daily_staffing(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(reports_service, "ReportsRepository", FakeReportsRepository)

    catalog = anyio.run(
        reports_service.list_report_catalog,
        FakeReportsRepository.users[UUID(int=1)],
    )
    assert any(module["code"] == "USERS" for module in catalog)

    report = anyio.run(
        reports_service.get_daily_staffing_report,
        cast(AsyncSession, object()),
        date(2026, 3, 24),
    )
    assert report["department_counts"] == [1]
    assert report["schedules"][0]["user"]["id"] == str(UUID(int=2))


def test_reports_financial_and_performance(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(reports_service, "ReportsRepository", FakeReportsRepository)

    async def _fake_payslip_summary(session, payslip_id):
        return {
            "net_salary": Decimal("500.00") if payslip_id == 1 else Decimal("0.00")
        }

    monkeypatch.setattr(reports_service, "get_payslip_summary", _fake_payslip_summary)

    yearly = anyio.run(
        reports_service.get_yearly_salary_expense_report,
        cast(AsyncSession, object()),
        2026,
    )
    assert yearly["total_expenses"] == 500.0

    performance = anyio.run(
        reports_service.get_employee_performance_summary,
        cast(AsyncSession, object()),
        2026,
        UUID(int=2),
        FakeReportsRepository.users[UUID(int=1)],
    )
    assert performance["self_rating_values"] == [4.0, 0]
    assert performance["peer_rating_values"] == [3.0, 0]


def test_reports_user_and_leave_summaries(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(reports_service, "ReportsRepository", FakeReportsRepository)

    leave_summary = anyio.run(
        reports_service.get_employee_leave_summary_report,
        cast(AsyncSession, object()),
        UUID(int=2),
        date(2026, 3, 1),
        date(2026, 3, 31),
        FakeReportsRepository.users[UUID(int=1)],
    )
    assert leave_summary["leave_counts"]["PA"] == 1

    demographics = anyio.run(
        reports_service.get_gender_demographics_report,
        cast(AsyncSession, object()),
        date(2026, 3, 24),
    )
    assert demographics["gender_group_counts"] == [0, 1]

    resignations = anyio.run(
        reports_service.get_resignation_report,
        cast(AsyncSession, object()),
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    assert len(resignations["rows"]) == 1
