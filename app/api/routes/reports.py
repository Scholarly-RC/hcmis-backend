from datetime import date
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db_session,
    require_hr_user,
    require_staff_user,
)
from app.models.user import User
from app.services.reports import (
    get_age_demographics_report,
    get_all_employees_report,
    get_daily_staffing_report,
    get_education_level_report,
    get_employee_leave_summary_report,
    get_employee_performance_summary,
    get_employee_yearly_salary_summary_report,
    get_employees_per_department_report,
    get_gender_demographics_report,
    get_payroll_summary_report,
    get_religion_report,
    list_report_catalog,
    get_resignation_report,
    get_yearly_salary_expense_report,
    get_years_of_experience_report,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/catalog")
async def read_report_catalog(
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    return cast(list[dict], await list_report_catalog(current_user))


@router.get("/attendance/daily-staffing")
async def read_daily_staffing_report(
    selected_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_daily_staffing_report(session, selected_date)


@router.get("/performance/employee-summary")
async def read_employee_performance_summary(
    selected_year: int,
    selected_user: UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await get_employee_performance_summary(session, selected_year, selected_user, current_user)


@router.get("/payroll/yearly-expense")
async def read_yearly_salary_expense_report(
    selected_year: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_yearly_salary_expense_report(session, selected_year)


@router.get("/payroll/summary")
async def read_payroll_summary_report(
    selected_month: int = Query(ge=1, le=12),
    selected_year: int = Query(ge=2000),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_hr_user),
) -> dict:
    return await get_payroll_summary_report(session, selected_month, selected_year)


@router.get("/payroll/employee-summary")
async def read_employee_yearly_salary_summary_report(
    selected_year: int,
    selected_user: UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await get_employee_yearly_salary_summary_report(
        session, selected_year, selected_user, current_user
    )


@router.get("/leave/employee-summary")
async def read_employee_leave_summary_report(
    selected_user: UUID,
    from_date: date,
    to_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await get_employee_leave_summary_report(
        session, selected_user, from_date, to_date, current_user
    )


@router.get("/users/all")
async def read_all_employees_report(
    as_of_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_all_employees_report(session, as_of_date)


@router.get("/users/by-department")
async def read_employees_per_department_report(
    as_of_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_employees_per_department_report(session, as_of_date)


@router.get("/users/demographics/age")
async def read_age_demographics_report(
    as_of_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_age_demographics_report(session, as_of_date)


@router.get("/users/demographics/gender")
async def read_gender_demographics_report(
    as_of_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_gender_demographics_report(session, as_of_date)


@router.get("/users/demographics/education")
async def read_education_level_report(
    as_of_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_education_level_report(session, as_of_date)


@router.get("/users/demographics/religion")
async def read_religion_report(
    as_of_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_religion_report(session, as_of_date)


@router.get("/users/years-of-experience")
async def read_years_of_experience_report(
    as_of_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_years_of_experience_report(session, as_of_date)


@router.get("/users/resignations")
async def read_resignation_report(
    from_date: date,
    to_date: date,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> dict:
    return await get_resignation_report(session, from_date, to_date)
