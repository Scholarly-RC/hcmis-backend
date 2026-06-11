from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.app_log import AppLog
from app.models.attendance import OvertimeRequest, OvertimeRequestApprover
from app.models.department import Department
from app.models.leave import (
    LeaveCredit,
    LeaveRequest,
    LeaveRequestApprover,
    LeaveRequestStatus,
    LeaveType,
)
from app.models.performance import Announcement, SharedResource
from app.models.user import User

TEST_PASSWORD = "qweasz123"


@dataclass(frozen=True)
class DepartmentSeed:
    code: str
    name: str


@dataclass(frozen=True)
class UserSeed:
    email: str
    first_name: str
    last_name: str
    employee_number: str
    role: str
    department_code: str
    is_superuser: bool = False


DEPARTMENTS: tuple[DepartmentSeed, ...] = (
    DepartmentSeed(code="HR", name="Human Resources"),
    DepartmentSeed(code="OPS", name="Operations"),
)

USERS: tuple[UserSeed, ...] = (
    UserSeed(
        email="admin@ndkc.edu.ph",
        first_name="Test",
        last_name="Admin",
        employee_number="ADM-001",
        role="HR",
        department_code="HR",
        is_superuser=True,
    ),
    UserSeed(
        email="hr@ndkc.edu.ph",
        first_name="Test",
        last_name="HR",
        employee_number="HR-001",
        role="HR",
        department_code="HR",
    ),
    UserSeed(
        email="employee@ndkc.edu.ph",
        first_name="Test",
        last_name="Employee",
        employee_number="EMP-001",
        role="EMP",
        department_code="OPS",
    ),
)


def _to_display_name(user: User) -> str:
    name = f"{user.first_name} {user.last_name}".strip()
    return name if name else user.email


async def _upsert_department(session: AsyncSession, seed: DepartmentSeed) -> Department:
    result = await session.execute(select(Department).where(Department.code == seed.code))
    department = result.scalar_one_or_none()

    if department is None:
        department = Department(code=seed.code, name=seed.name)
        session.add(department)
        await session.flush()
        return department

    department.name = seed.name
    return department


async def _upsert_user(
    session: AsyncSession,
    seed: UserSeed,
    department: Department,
    password_hash: str,
) -> User:
    result = await session.execute(select(User).where(User.email == seed.email.lower()))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            email=seed.email.lower(),
            password_hash=password_hash,
            first_name=seed.first_name,
            last_name=seed.last_name,
            employee_number=seed.employee_number,
            role=seed.role,
            department_id=department.id,
            can_modify_shift=False,
            is_active=True,
            is_superuser=seed.is_superuser,
        )
        session.add(user)
        await session.flush()
        return user

    user.password_hash = password_hash
    user.first_name = seed.first_name
    user.last_name = seed.last_name
    user.employee_number = seed.employee_number
    user.role = seed.role
    user.department_id = department.id
    user.can_modify_shift = False
    user.is_active = True
    user.is_superuser = seed.is_superuser
    return user


async def _upsert_leave_credit(
    session: AsyncSession,
    user_id: UUID,
    credits: int,
    used_credits: int,
) -> LeaveCredit:
    result = await session.execute(select(LeaveCredit).where(LeaveCredit.user_id == user_id))
    leave_credit = result.scalar_one_or_none()

    if leave_credit is None:
        leave_credit = LeaveCredit(
            user_id=user_id,
            credits=credits,
            used_credits=used_credits,
        )
        session.add(leave_credit)
        await session.flush()
        return leave_credit

    leave_credit.credits = credits
    leave_credit.used_credits = used_credits
    return leave_credit


async def seed_initial_data(session: AsyncSession) -> None:
    password_hash = hash_password(TEST_PASSWORD)

    departments = {
        seed.code: await _upsert_department(session, seed) for seed in DEPARTMENTS
    }
    users = {
        seed.email.lower(): await _upsert_user(
            session,
            seed,
            departments[seed.department_code],
            password_hash,
        )
        for seed in USERS
    }

    employee = users["employee@ndkc.edu.ph"]
    hr_user = users["hr@ndkc.edu.ph"]

    await _upsert_leave_credit(session, employee.id, credits=15, used_credits=3)
    session.add(
        LeaveRequest(
            user_id=employee.id,
            leave_date=date.today(),
            leave_type=LeaveType.PAID.value,
            info="Seeded leave request",
            first_approver_id=hr_user.id,
            first_approver_status=LeaveRequestStatus.PENDING.value,
            status=LeaveRequestStatus.PENDING.value,
            approver_pool=[
                LeaveRequestApprover(
                    approver_id=hr_user.id,
                    status=LeaveRequestStatus.PENDING.value,
                )
            ],
        )
    )

    session.add(
        OvertimeRequest(
            user_id=employee.id,
            approver_id=hr_user.id,
            date=date.today(),
            info="Seeded overtime request",
            status=OvertimeRequest.Status.PENDING.value,
            approver_pool=[
                OvertimeRequestApprover(
                    approver_id=hr_user.id,
                    status=OvertimeRequest.Status.PENDING.value,
                )
            ],
        )
    )

    session.add(
        AppLog(
            user_id=hr_user.id,
            details="Seeded app log entry for QA automation.",
        )
    )

    session.add(
        Announcement(
            author_id=hr_user.id,
            title="Welcome to HCMIS QA Seed",
            summary="Baseline announcement for dashboard feed checks.",
            content="This record is created by the seed command.",
            status="published",
            published_at=datetime.now(UTC),
        )
    )

    session.add(
        SharedResource(
            uploader_id=hr_user.id,
            resource_name="Seeded HR Policy",
            description="Sample shared resource used for test verification.",
            storage_key="seed/hr-policy.txt",
            original_filename="hr-policy.txt",
            content_type="text/plain",
            size_bytes=21,
            is_confidential=False,
        )
    )

    await session.commit()

    print("Seeded initial testing data:")
    for user in users.values():
        print(f"- {user.email} ({_to_display_name(user)})")
    print(f"Shared password: {TEST_PASSWORD}")
