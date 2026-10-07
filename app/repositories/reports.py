from uuid import UUID

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import DepartmentRosterDay, EmployeeShiftAssignment
from app.models.department import Department
from app.models.leave import LeaveRequest
from app.models.performance import Evaluation, UserEvaluation
from app.models.payroll import Payslip
from app.models.user import User


class ReportsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user(self, user_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).options(selectinload(User.department)).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        as_of_date: date | None = None,
        active_only: bool = True,
        include_superusers: bool = False,
    ) -> list[User]:
        statement = select(User).options(selectinload(User.department))
        if active_only:
            statement = statement.where(User.is_active.is_(True))
        if not include_superusers:
            statement = statement.where(User.is_superuser.is_(False))
        if as_of_date is not None:
            statement = statement.where(
                or_(
                    User.date_of_hiring.is_(None),
                    User.date_of_hiring <= as_of_date,
                )
            )
        statement = statement.order_by(User.first_name.asc(), User.last_name.asc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_departments(self) -> list[Department]:
        result = await self.session.execute(
            select(Department)
            .options(
                selectinload(Department.users),
                selectinload(Department.department_roster_days).selectinload(
                    DepartmentRosterDay.employee_shift_assignments
                ),
            )
            .order_by(Department.name.asc())
        )
        return list(result.scalars().unique().all())

    async def list_daily_shift_records(
        self, selected_date: date
    ) -> list[DepartmentRosterDay]:
        result = await self.session.execute(
            select(DepartmentRosterDay)
            .options(
                selectinload(DepartmentRosterDay.department),
                selectinload(DepartmentRosterDay.employee_shift_assignments)
                .selectinload(EmployeeShiftAssignment.user)
                .selectinload(User.department),
                selectinload(DepartmentRosterDay.employee_shift_assignments).selectinload(
                    EmployeeShiftAssignment.shift_template
                ),
            )
            .where(DepartmentRosterDay.date == selected_date)
            .order_by(DepartmentRosterDay.department_id.asc())
        )
        return list(result.scalars().unique().all())

    async def list_leave_requests(
        self,
        user_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[LeaveRequest]:
        statement = (
            select(LeaveRequest)
            .options(selectinload(LeaveRequest.user).selectinload(User.department))
            .order_by(LeaveRequest.leave_date.asc())
        )
        if user_id is not None:
            statement = statement.where(LeaveRequest.user_id == user_id)
        if from_date is not None:
            statement = statement.where(LeaveRequest.leave_date >= from_date)
        if to_date is not None:
            statement = statement.where(LeaveRequest.leave_date <= to_date)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_payslips(
        self,
        user_id: UUID | None = None,
        year: int | None = None,
        released: bool | None = True,
        month: int | None = None,
    ) -> list[Payslip]:
        statement = (
            select(Payslip)
            .options(
                selectinload(Payslip.user).selectinload(User.department),
                selectinload(Payslip.variable_compensations),
                selectinload(Payslip.variable_deductions),
            )
            .order_by(Payslip.month.asc(), Payslip.period.asc())
        )
        if user_id is not None:
            statement = statement.where(Payslip.user_id == user_id)
        if month is not None:
            statement = statement.where(Payslip.month == month)
        if year is not None:
            statement = statement.where(Payslip.year == year)
        if released is not None:
            statement = statement.where(Payslip.released.is_(released))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_user_evaluations(
        self,
        user_id: UUID | None = None,
        year: int | None = None,
        finalized: bool | None = True,
    ) -> list[UserEvaluation]:
        statement = (
            select(UserEvaluation)
            .options(
                selectinload(UserEvaluation.evaluatee).selectinload(User.department),
                selectinload(UserEvaluation.questionnaire),
                selectinload(UserEvaluation.evaluations)
                .selectinload(Evaluation.evaluator)
                .selectinload(User.department),
                selectinload(UserEvaluation.evaluations).selectinload(Evaluation.questionnaire),
            )
            .order_by(UserEvaluation.year.asc(), UserEvaluation.quarter.asc())
        )
        if user_id is not None:
            statement = statement.where(UserEvaluation.evaluatee_id == user_id)
        if year is not None:
            statement = statement.where(UserEvaluation.year == year)
        if finalized is not None:
            statement = statement.where(UserEvaluation.is_finalized.is_(finalized))
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())
