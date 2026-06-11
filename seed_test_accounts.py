from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
import app.db.base  # noqa: F401
from app.core.security import hash_password
from app.db.session import async_session_maker
from app.models.department import Department
from app.models.user import User

TEST_PASSWORD = "qweasz123"


@dataclass(frozen=True)
class SeedAccount:
    email: str
    first_name: str
    last_name: str
    employee_number: str
    role: str
    department_name: str
    department_code: str
    is_superuser: bool = False


SEED_ACCOUNTS: tuple[SeedAccount, ...] = (
    SeedAccount(
        email="admin@ndkc.edu.ph",
        first_name="Test",
        last_name="Admin",
        employee_number="ADM-001",
        role="HR",
        department_name="Human Resources",
        department_code="HR",
        is_superuser=True,
    ),
    SeedAccount(
        email="hr@ndkc.edu.ph",
        first_name="Test",
        last_name="HR",
        employee_number="HR-001",
        role="HR",
        department_name="Human Resources",
        department_code="HR",
    ),
    SeedAccount(
        email="employee@ndkc.edu.ph",
        first_name="Test",
        last_name="Employee",
        employee_number="EMP-001",
        role="EMP",
        department_name="Operations",
        department_code="OPS",
    ),
)

async def upsert_department(session: AsyncSession, name: str, code: str) -> Department:
    result = await session.execute(select(Department).where(Department.code == code))
    department = result.scalar_one_or_none()
    if department is None:
        department = Department(name=name, code=code)
        session.add(department)
        await session.flush()
        return department

    department.name = name
    department.code = code
    return department


async def upsert_user(
    session: AsyncSession,
    account: SeedAccount,
    department: Department,
) -> User:
    result = await session.execute(
        select(User).where(User.email == account.email.lower())
    )
    user = result.scalar_one_or_none()
    password_hash = hash_password(TEST_PASSWORD)

    if user is None:
        user = User(
            email=account.email.lower(),
            password_hash=password_hash,
            first_name=account.first_name,
            last_name=account.last_name,
            employee_number=account.employee_number,
            role=account.role,
            department_id=department.id,
            can_modify_shift=False,
            is_active=True,
            is_superuser=account.is_superuser,
        )
        session.add(user)
        await session.flush()
        return user

    user.password_hash = password_hash
    user.first_name = account.first_name
    user.last_name = account.last_name
    user.employee_number = account.employee_number
    user.role = account.role
    user.department_id = department.id
    user.can_modify_shift = False
    user.is_active = True
    user.is_superuser = account.is_superuser
    return user


async def seed_test_accounts() -> None:
    async with async_session_maker() as session:
        created_users: list[User] = []
        departments: dict[str, Department] = {}

        for account in SEED_ACCOUNTS:
            if account.department_code not in departments:
                departments[account.department_code] = await upsert_department(
                    session,
                    name=account.department_name,
                    code=account.department_code,
                )

            created_users.append(
                await upsert_user(session, account, departments[account.department_code])
            )

        await session.commit()

    print("Seeded test accounts:")
    for user in created_users:
        print(f"- {user.email}")
    print(f"Shared password: {TEST_PASSWORD}")


def main() -> None:
    asyncio.run(seed_test_accounts())


if __name__ == "__main__":
    main()
