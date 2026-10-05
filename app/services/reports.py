from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import TypedDict, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import is_hr_user, is_staff_user
from app.core.exceptions import NotFoundError
from app.models.leave import LeaveType
from app.models.performance import Evaluation
from app.models.user import User
from app.repositories.reports import ReportsRepository
from app.schemas.department import DepartmentRead
from app.schemas.user import UserRead
from app.services.payroll import get_payslip_summary
from app.services.payroll_engine import get_payslip_summary_v2

MONTH_LABELS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

EDUCATION_LABELS = {
    "HS": "High School",
    "VC": "Vocational",
    "BA": "Bachelor",
    "MA": "Master",
    "DR": "Doctorate",
}

RELIGION_LABELS = {
    "RC": "Roman Catholic",
    "IS": "Islam",
    "EV": "Evangelical",
    "INC": "Iglesia ni Cristo",
    "AG": "Aglipayan",
    "JW": "Jehovah's Witnesses",
    "BAC": "Born Again Christian",
    "SDA": "Seventh-day Adventist",
    "UPC": "United Pentecostal Church",
    "BAP": "Baptist",
    "MET": "Methodist",
    "COC": "Church of Christ",
}


class ReportCatalogEntry(TypedDict):
    code: str
    label: str


class ReportCatalogModule(TypedDict):
    code: str
    label: str
    reports: list[ReportCatalogEntry]


REPORT_CATALOG: list[ReportCatalogModule] = [
    {
        "code": "ATTENDANCE",
        "label": "Attendance",
        "reports": [
            {"code": "DAILY_STAFFING_REPORT", "label": "Daily Staffing Report"},
        ],
    },
    {
        "code": "PERFORMANCE_AND_LEARNING",
        "label": "Performance and Learning",
        "reports": [
            {
                "code": "EMPLOYEE_PERFORMANCE_SUMMARY",
                "label": "Employee Performance Summary",
            }
        ],
    },
    {
        "code": "PAYROLL",
        "label": "Payroll",
        "reports": [
            {"code": "YEARLY_SALARY_EXPENSE", "label": "Yearly Salary Expense"},
            {"code": "PAYROLL_SUMMARY", "label": "Payroll Summary"},
            {
                "code": "EMPLOYEE_YEARLY_SALARY_SUMMARY",
                "label": "Employee Yearly Salary Summary",
            },
        ],
    },
    {
        "code": "LEAVE",
        "label": "Leave",
        "reports": [
            {"code": "EMPLOYEE_LEAVE_SUMMARY", "label": "Employee Leave Summary"},
        ],
    },
    {
        "code": "USERS",
        "label": "Users",
        "reports": [
            {"code": "ALL_EMPLOYEES", "label": "All Employees"},
            {
                "code": "EMPLOYEES_PER_DEPARTMENT",
                "label": "Employees Per Department",
            },
            {"code": "AGE", "label": "Age Demographics"},
            {"code": "GENDER", "label": "Gender Demographics"},
            {"code": "YEARS_OF_EXPERIENCE", "label": "Years of Experience"},
            {"code": "EDUCATION_LEVEL", "label": "Education Level"},
            {"code": "RELIGION", "label": "Religion"},
            {"code": "RESIGNATION", "label": "Resignation"},
        ],
    },
]


def _user_dict(user: User) -> dict:
    return UserRead.model_validate(user).model_dump(mode="json")


def _department_dict(department) -> dict:
    return DepartmentRead.model_validate(department).model_dump(mode="json")


def _as_date(value: date | str | None) -> date:
    if isinstance(value, date):
        return value
    if value is None or value == "":
        return date.today()
    return date.fromisoformat(value)


def _age(date_of_birth: date, as_of_date: date) -> int:
    return (
        as_of_date.year
        - date_of_birth.year
        - ((as_of_date.month, as_of_date.day) < (date_of_birth.month, date_of_birth.day))
    )


def _years_of_service(date_of_hiring: date, as_of_date: date) -> int:
    return as_of_date.year - date_of_hiring.year


def _evaluation_score(evaluation: Evaluation) -> float:
    total = 0.0
    count = 0
    for domain in evaluation.content_data or []:
        for question in domain.get("questions", []):
            rating = question.get("rating")
            if rating in (None, "", False):
                continue
            total += float(rating)
            count += 1
    return round(total / count, 2) if count else 0.0


async def list_report_catalog(current_user: User) -> list[ReportCatalogModule]:
    is_hr = is_staff_user(current_user)
    has_payroll_summary_access = is_hr_user(current_user)
    modules: list[ReportCatalogModule] = []
    for module in REPORT_CATALOG:
        if module["code"] == "USERS" and not is_hr:
            continue
        if module["code"] == "ATTENDANCE" and not is_hr:
            modules.append(
                {
                    "code": module["code"],
                    "label": module["label"],
                    "reports": [],
                }
            )
            continue
        if module["code"] == "PAYROLL" and not has_payroll_summary_access:
            modules.append(
                {
                    "code": module["code"],
                    "label": module["label"],
                    "reports": [
                        report
                        for report in module["reports"]
                        if report["code"] != "PAYROLL_SUMMARY"
                    ],
                }
            )
            continue
        modules.append(module)
    return modules


async def get_daily_staffing_report(
    session: AsyncSession, selected_date: date | str
) -> dict:
    report_repo = ReportsRepository(session)
    selected_date_value = _as_date(selected_date)
    records = await report_repo.list_daily_shift_records(selected_date_value)
    departments = await report_repo.list_departments()
    department_counts = []
    department_labels = []
    schedules = []
    record_map = {record.department_id: record for record in records}
    for department in departments:
        department_labels.append(department.name)
        record = record_map.get(department.id)
        department_counts.append(len(record.schedules) if record else 0)
        if record:
            for schedule in record.schedules:
                schedules.append(
                    {
                        "department": _department_dict(department),
                        "user": _user_dict(schedule.user),
                        "shift": {
                            "id": schedule.shift.id,
                            "description": schedule.shift.description,
                            "start_time": schedule.shift.start_time.isoformat()
                            if schedule.shift.start_time
                            else None,
                            "end_time": schedule.shift.end_time.isoformat()
                            if schedule.shift.end_time
                            else None,
                        },
                        "date": schedule.date.isoformat(),
                    }
                )
    return {
        "selected_date": selected_date_value.isoformat(),
        "department_labels": department_labels,
        "department_counts": department_counts,
        "schedules": schedules,
    }


async def get_employee_performance_summary(
    session: AsyncSession, selected_year: int, selected_user: UUID, current_user: User
) -> dict:
    report_repo = ReportsRepository(session)
    if not is_staff_user(current_user) and current_user.id != selected_user:
        selected_user = current_user.id
    evaluations = await report_repo.list_user_evaluations(
        user_id=selected_user, year=selected_year, finalized=True
    )
    quarters = ["FQ", "SQ"]
    self_rating_values = []
    peer_rating_values = []
    for quarter in quarters:
        user_evaluation = next((item for item in evaluations if item.quarter == quarter), None)
        if user_evaluation is None:
            self_rating_values.append(0)
            peer_rating_values.append(0)
            continue
        self_scores = []
        peer_scores = []
        for evaluation in user_evaluation.evaluations:
            score = _evaluation_score(evaluation)
            if evaluation.evaluator_id == user_evaluation.evaluatee_id:
                self_scores.append(score)
            else:
                peer_scores.append(score)
        self_rating_values.append(round(sum(self_scores) / len(self_scores), 2) if self_scores else 0)
        peer_rating_values.append(round(sum(peer_scores) / len(peer_scores), 2) if peer_scores else 0)
    return {
        "selected_year": selected_year,
        "selected_user": _user_dict(evaluations[0].evaluatee) if evaluations else None,
        "quarters": quarters,
        "self_rating_values": self_rating_values,
        "peer_rating_values": peer_rating_values,
    }


async def get_yearly_salary_expense_report(session: AsyncSession, selected_year: int) -> dict:
    report_repo = ReportsRepository(session)
    payslips = await report_repo.list_payslips(year=selected_year, released=True)
    monthly_totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    total_expense = Decimal("0.00")
    for payslip in payslips:
        summary = await get_payslip_summary(session, payslip.id)
        net_salary = summary["net_salary"] or Decimal("0.00")
        month = payslip.month or 0
        monthly_totals[month] += net_salary
        total_expense += net_salary
    months = [MONTH_LABELS[month - 1] for month in sorted(monthly_totals)]
    totals = [float(monthly_totals[month].quantize(Decimal("0.01"))) for month in sorted(monthly_totals)]
    return {
        "selected_year": selected_year,
        "months": months,
        "total_amounts": totals,
        "total_expenses": float(total_expense.quantize(Decimal("0.01"))),
    }


def _summary_value(summary: object, key: str) -> Decimal:
    if isinstance(summary, Mapping):
        value = cast(Mapping[str, object], summary).get(key)
    else:
        value = getattr(summary, key, None)
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _empty_payroll_totals() -> dict[str, Decimal]:
    return {
        "gross_pay": Decimal("0.00"),
        "total_deductions": Decimal("0.00"),
        "net_salary": Decimal("0.00"),
    }


def _add_payroll_totals(target: dict[str, Decimal], source: dict[str, Decimal]) -> None:
    for key in target:
        target[key] += source[key]


def _serialize_payroll_totals(values: dict[str, Decimal]) -> dict[str, float]:
    return {
        key: float(value.quantize(Decimal("0.01")))
        for key, value in values.items()
    }


async def get_payroll_summary_report(
    session: AsyncSession, selected_month: int, selected_year: int
) -> dict:
    report_repo = ReportsRepository(session)
    payslips = await report_repo.list_payslips(
        month=selected_month,
        year=selected_year,
        released=True,
    )
    rows_by_user: dict[UUID, dict] = {}
    report_totals = {
        "first_cutoff": _empty_payroll_totals(),
        "second_cutoff": _empty_payroll_totals(),
        "monthly_total": _empty_payroll_totals(),
    }

    for payslip in payslips:
        cutoff_key = {
            "1ST": "first_cutoff",
            "2ND": "second_cutoff",
        }.get(payslip.period or "")
        if cutoff_key is None or payslip.user is None:
            continue

        summary = await get_payslip_summary_v2(session, payslip.id)
        totals = {
            "gross_pay": _summary_value(summary, "gross_pay"),
            "total_deductions": _summary_value(summary, "total_deductions"),
            "net_salary": _summary_value(summary, "net_salary"),
        }
        row = rows_by_user.setdefault(
            payslip.user_id,
            {
                "user": _user_dict(payslip.user),
                "first_cutoff": None,
                "second_cutoff": None,
                "monthly_total": _empty_payroll_totals(),
            },
        )
        row[cutoff_key] = {
            "payslip_id": payslip.id,
            **_serialize_payroll_totals(totals),
        }
        _add_payroll_totals(row["monthly_total"], totals)
        _add_payroll_totals(report_totals[cutoff_key], totals)
        _add_payroll_totals(report_totals["monthly_total"], totals)

    rows = sorted(
        rows_by_user.values(),
        key=lambda row: (
            row["user"].get("last_name") or "",
            row["user"].get("first_name") or "",
        ),
    )
    serialized_rows = [
        {
            **row,
            "monthly_total": _serialize_payroll_totals(row["monthly_total"]),
        }
        for row in rows
    ]

    return {
        "selected_month": selected_month,
        "selected_year": selected_year,
        "employee_count": len(serialized_rows),
        "rows": serialized_rows,
        "totals": {
            key: _serialize_payroll_totals(value)
            for key, value in report_totals.items()
        },
    }


async def get_employee_yearly_salary_summary_report(
    session: AsyncSession, selected_year: int, selected_user: UUID, current_user: User
) -> dict:
    report_repo = ReportsRepository(session)
    if not is_staff_user(current_user) and current_user.id != selected_user:
        selected_user = current_user.id
    payslips = await report_repo.list_payslips(
        user_id=selected_user, year=selected_year, released=True
    )
    monthly_totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    total_salary = Decimal("0.00")
    for payslip in payslips:
        summary = await get_payslip_summary(session, payslip.id)
        net_salary = summary["net_salary"] or Decimal("0.00")
        month = payslip.month or 0
        monthly_totals[month] += net_salary
        total_salary += net_salary
    months = [MONTH_LABELS[month - 1] for month in sorted(monthly_totals)]
    totals = [float(monthly_totals[month].quantize(Decimal("0.01"))) for month in sorted(monthly_totals)]
    return {
        "selected_year": selected_year,
        "selected_user": _user_dict(payslips[0].user) if payslips else None,
        "months": months,
        "total_amounts": totals,
        "total_salary": float(total_salary.quantize(Decimal("0.01"))),
    }


async def get_employee_leave_summary_report(
    session: AsyncSession,
    selected_user: UUID,
    from_date: date | str,
    to_date: date | str,
    current_user: User,
) -> dict:
    report_repo = ReportsRepository(session)
    if not is_staff_user(current_user) and current_user.id != selected_user:
        selected_user = current_user.id
    from_date_value = _as_date(from_date)
    to_date_value = _as_date(to_date)
    user = await report_repo.get_user(selected_user)
    if user is None:
        raise NotFoundError("User not found.")
    leaves = await report_repo.list_leave_requests(
        user_id=selected_user, from_date=from_date_value, to_date=to_date_value
    )
    counts = Counter(leave.leave_type for leave in leaves)
    return {
        "selected_user": _user_dict(user),
        "from_date": from_date_value.isoformat(),
        "to_date": to_date_value.isoformat(),
        "leave_counts": {
            "PA": counts.get(LeaveType.PAID.value, 0),
            "UN": counts.get(LeaveType.UNPAID.value, 0),
            "WR": counts.get(LeaveType.WORK_RELATED_TRIP.value, 0),
        },
        "leaves": [
            {
                "id": leave.id,
                "leave_date": leave.leave_date.isoformat(),
                "leave_type": leave.leave_type,
                "status": leave.status,
                "info": leave.info,
            }
            for leave in leaves
        ],
    }


async def get_all_employees_report(session: AsyncSession, as_of_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    as_of_date_value = _as_date(as_of_date)
    users = await report_repo.list_users(as_of_date=as_of_date_value)
    return {
        "as_of_date": as_of_date_value.isoformat(),
        "users": [_user_dict(user) for user in users],
    }


async def get_employees_per_department_report(session: AsyncSession, as_of_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    as_of_date_value = _as_date(as_of_date)
    users = await report_repo.list_users(as_of_date=as_of_date_value)
    departments = await report_repo.list_departments()
    counts = Counter(user.department_id for user in users if user.department_id is not None)
    return {
        "as_of_date": as_of_date_value.isoformat(),
        "departments": [_department_dict(department) for department in departments],
        "department_counts": [
            counts.get(department.id, 0) for department in departments
        ],
    }


async def get_age_demographics_report(session: AsyncSession, as_of_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    as_of_date_value = _as_date(as_of_date)
    users = await report_repo.list_users(as_of_date=as_of_date_value)
    rows = []
    age_groups = ["18-24", "25-39", "40-54", "55-64", "65-Up"]
    counts = Counter()
    for user in users:
        if user.date_of_birth is None:
            continue
        age = _age(user.date_of_birth, as_of_date_value)
        rows.append({"user": _user_dict(user), "age": age})
        if 18 <= age <= 24:
            counts["18-24"] += 1
        elif 25 <= age <= 39:
            counts["25-39"] += 1
        elif 40 <= age <= 54:
            counts["40-54"] += 1
        elif 55 <= age <= 64:
            counts["55-64"] += 1
        elif age >= 65:
            counts["65-Up"] += 1
    return {
        "as_of_date": as_of_date_value.isoformat(),
        "age_groups": age_groups,
        "age_group_counts": [counts[group] for group in age_groups],
        "rows": rows,
    }


async def get_gender_demographics_report(session: AsyncSession, as_of_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    as_of_date_value = _as_date(as_of_date)
    users = await report_repo.list_users(as_of_date=as_of_date_value)
    counts = Counter(user.gender for user in users if user.gender)
    return {
        "as_of_date": as_of_date_value.isoformat(),
        "gender_groups": ["Male", "Female"],
        "gender_group_counts": [counts.get("M", 0), counts.get("F", 0)],
    }


async def get_years_of_experience_report(session: AsyncSession, as_of_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    as_of_date_value = _as_date(as_of_date)
    users = await report_repo.list_users(as_of_date=as_of_date_value)
    rows = []
    years = []
    for user in users:
        if user.date_of_hiring is None:
            continue
        years_of_experience = _years_of_service(user.date_of_hiring, as_of_date_value)
        rows.append({"user": _user_dict(user), "years_of_experience": years_of_experience})
        years.append(years_of_experience)
    year_groups = sorted(set(years))
    counts = [years.count(year) for year in year_groups]
    average = round(sum(years) / len(years), 2) if years else 0
    return {
        "as_of_date": as_of_date_value.isoformat(),
        "years_of_experience_groups": year_groups,
        "years_of_experience_counts": counts,
        "years_of_experience_average": average,
        "rows": rows,
    }


async def get_education_level_report(session: AsyncSession, as_of_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    as_of_date_value = _as_date(as_of_date)
    users = await report_repo.list_users(as_of_date=as_of_date_value)
    counts = Counter(
        user.highest_education_level for user in users if user.highest_education_level
    )
    labels = [EDUCATION_LABELS.get(code, code) for code in counts.keys()]
    values = [counts[code] for code in counts.keys()]
    return {
        "as_of_date": as_of_date_value.isoformat(),
        "education_labels": labels,
        "education_counts": values,
    }


async def get_religion_report(session: AsyncSession, as_of_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    as_of_date_value = _as_date(as_of_date)
    users = await report_repo.list_users(as_of_date=as_of_date_value)
    counts = Counter(user.religion for user in users if user.religion)
    labels = [RELIGION_LABELS.get(code, code) for code in counts.keys()]
    values = [counts[code] for code in counts.keys()]
    return {
        "as_of_date": as_of_date_value.isoformat(),
        "religion_labels": labels,
        "religion_counts": values,
    }


async def get_resignation_report(session: AsyncSession, from_date: date | str, to_date: date | str) -> dict:
    report_repo = ReportsRepository(session)
    from_date_value = _as_date(from_date)
    to_date_value = _as_date(to_date)
    users = await report_repo.list_users(active_only=False, include_superusers=True)
    rows = [
        {
            "user": _user_dict(user),
            "resignation_date": user.resignation_date.isoformat() if user.resignation_date else None,
        }
        for user in users
        if user.resignation_date and from_date_value <= user.resignation_date <= to_date_value
    ]
    rows.sort(key=lambda item: item["resignation_date"] or "")
    return {
        "from_date": from_date_value.isoformat(),
        "to_date": to_date_value.isoformat(),
        "rows": rows,
    }
