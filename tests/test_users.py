import anyio
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.time import utc_now
from app.models.department import Department
from app.models.payroll import Position
from app.models.user import User
from app.models.user import UserEmploymentMovement
from app.models.user import UserPositionAssignment
from app.models.user import UserSalaryAssignment
from app.schemas.user import UserBiometricUpdateRequest
from app.schemas.user import UserUpdateRequest
from app.services import users as user_service


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

    async def list(
        self,
        query=None,
        department_id=None,
        active_only=None,
        include_superusers=False,
        exclude_hr=False,
        exclude_user_id=None,
    ):
        users = list(self.users.values())
        if not include_superusers:
            users = [user for user in users if not user.is_superuser]
        if exclude_hr:
            users = [
                user
                for user in users
                if (user.role or "").strip().upper() != "HR"
                and (getattr(user.department, "code", "") or "").strip().upper()
                != "HR"
                and (getattr(user.department, "name", "") or "").strip().upper()
                != "HR"
            ]
        if exclude_user_id is not None:
            users = [user for user in users if user.id != exclude_user_id]
        if department_id is not None:
            users = [user for user in users if user.department_id == department_id]
        if active_only is True:
            users = [user for user in users if user.is_active]
        if query:
            lowered = query.lower()
            users = [
                user
                for user in users
                if lowered in user.first_name.lower()
                or lowered in user.last_name.lower()
                or lowered in user.email.lower()
                or (user.employee_number and lowered in user.employee_number.lower())
            ]
        return sorted(
            users,
            key=lambda user: (
                user.department.name if getattr(user, "department", None) else "",
                user.first_name,
                user.last_name,
            ),
        )

    async def get_by_id(self, user_id: UUID):
        return self.users.get(user_id)

    async def save(self, user: User):
        user.updated_at = utc_now()
        self.users[user.id] = user
        return user


class FakePositionRepository:
    positions: dict[int, Position] = {}

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, position_id: int):
        return self.positions.get(position_id)


class FakeUserPositionAssignmentRepository:
    items: dict[int, UserPositionAssignment] = {}
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

    async def get_overlapping_assignments(self, user_id: UUID, effective_from, effective_to, exclude_assignment_id=None):
        return [
            item
            for item in self.items.values()
            if item.user_id == user_id
            and item.id != exclude_assignment_id
            and (item.effective_to is None or item.effective_to >= effective_from)
        ]

    async def create(self, assignment: UserPositionAssignment):
        assignment.id = self.next_id
        self.next_id += 1
        self.items[assignment.id] = assignment
        return assignment

    async def save(self, assignment: UserPositionAssignment):
        self.items[assignment.id] = assignment
        return assignment


class FakeUserSalaryAssignmentRepository:
    items: dict[int, UserSalaryAssignment] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def get_overlapping_assignments(
        self,
        user_id: UUID,
        effective_from,
        effective_to,
        exclude_assignment_id=None,
    ):
        return [
            item
            for item in self.items.values()
            if item.user_id == user_id
            and item.id != exclude_assignment_id
            and (item.effective_to is None or item.effective_to >= effective_from)
        ]

    async def create(self, assignment: UserSalaryAssignment):
        assignment.id = self.next_id
        self.next_id += 1
        self.items[assignment.id] = assignment
        return assignment

    async def save(self, assignment: UserSalaryAssignment):
        self.items[assignment.id] = assignment
        return assignment


class FakeUserEmploymentMovementRepository:
    items: list[UserEmploymentMovement] = []

    def __init__(self, session):
        self.session = session

    async def create_many(self, movements: list[UserEmploymentMovement]):
        self.items.extend(movements)
        return movements


async def _list_users(
    query: str | None = None,
    department_id: int | None = None,
    active_only: bool | None = None,
    exclude_hr: bool = False,
    exclude_user_id: UUID | None = None,
):
    return await user_service.list_users(
        session=cast(AsyncSession, object()),
        query=query,
        department_id=department_id,
        active_only=active_only,
        exclude_hr=exclude_hr,
        exclude_user_id=exclude_user_id,
    )


async def _update_user(user_id: UUID, payload: UserUpdateRequest):
    return await user_service.update_user(
        session=cast(AsyncSession, object()),
        user_id=user_id,
        payload=payload,
        actor_user_id=UUID(int=99),
    )


async def _toggle_user(user_id: UUID):
    return await user_service.toggle_user_status(
        session=cast(AsyncSession, object()),
        user_id=user_id,
    )


async def _update_biometric(user_id: UUID, payload: UserBiometricUpdateRequest):
    return await user_service.update_user_biometric_uid(
        session=cast(AsyncSession, object()),
        user_id=user_id,
        payload=payload,
    )


def setup_function():
    FakeDepartmentRepository.departments = {}
    FakeUserRepository.users = {}
    FakePositionRepository.positions = {}
    FakeUserPositionAssignmentRepository.items = {}
    FakeUserPositionAssignmentRepository.next_id = 1
    FakeUserSalaryAssignmentRepository.items = {}
    FakeUserSalaryAssignmentRepository.next_id = 1
    FakeUserEmploymentMovementRepository.items = []


def _make_department(department_id: int, name: str):
    department = Department(name=name, code=name[:3].upper(), is_active=True)
    department.id = department_id
    return department


def _make_position(position_id: int, code: str, title: str = "Position"):
    position = Position(
        id=position_id,
        code=code,
        title=title,
        is_active=True,
    )
    position.departments = []
    return position


def _make_user(
    user_id: UUID,
    first_name: str,
    last_name: str,
    email: str,
    department: Department | None = None,
    department_id: int | None = None,
    is_active: bool = True,
    is_superuser: bool = False,
):
    user = User(
        id=user_id,
        email=email,
        password_hash="hashed",
        first_name=first_name,
        last_name=last_name,
        can_modify_shift=False,
        department_id=department_id,
        is_active=is_active,
        is_superuser=is_superuser,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    user.department = department
    return user


def test_list_users_filters_and_orders(monkeypatch):
    accounting = _make_department(1, "Accounting")
    hr = _make_department(2, "Human Resources")

    first = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", accounting, 1)
    second = _make_user(UUID(int=2), "Charlie", "C", "charlie@example.com", accounting, 1)
    third = _make_user(UUID(int=3), "Bob", "B", "bob@example.com", hr, 2)
    superuser = _make_user(UUID(int=4), "Admin", "User", "admin@example.com", hr, 2, is_superuser=True)

    FakeUserRepository.users = {
        first.id: first,
        second.id: second,
        third.id: third,
        superuser.id: superuser,
    }

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)

    response = anyio.run(_list_users)

    assert [user.first_name for user in response] == ["Alice", "Charlie", "Bob"]


def test_list_users_can_exclude_hr_users(monkeypatch):
    accounting = _make_department(1, "Accounting")
    hr = _make_department(2, "Human Resources")

    emp = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", accounting, 1)
    hr_role = _make_user(UUID(int=2), "Bob", "B", "bob@example.com", accounting, 1)
    hr_role.role = "HR"
    hr_department = _make_user(UUID(int=3), "Cara", "C", "cara@example.com", hr, 2)

    FakeUserRepository.users = {
        emp.id: emp,
        hr_role.id: hr_role,
        hr_department.id: hr_department,
    }

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)

    response = anyio.run(_list_users, None, None, None, True)

    assert [user.email for user in response] == [
        "alice@example.com",
        "cara@example.com",
    ]


def test_list_users_supports_query_and_department_filters(monkeypatch):
    accounting = _make_department(1, "Accounting")
    hr = _make_department(2, "Human Resources")
    alice = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", accounting, 1)
    bob = _make_user(UUID(int=2), "Bob", "B", "bob@example.com", hr, 2)

    FakeUserRepository.users = {alice.id: alice, bob.id: bob}
    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)

    response = anyio.run(
        _list_users,
        "bo",
        2,
        True,
    )

    assert [user.email for user in response] == ["bob@example.com"]


def test_list_users_can_exclude_a_specific_user(monkeypatch):
    accounting = _make_department(1, "Accounting")
    alice = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", accounting, 1)
    bob = _make_user(UUID(int=2), "Bob", "B", "bob@example.com", accounting, 1)

    FakeUserRepository.users = {alice.id: alice, bob.id: bob}
    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)

    response = anyio.run(_list_users, None, None, None, False, UUID(int=2))

    assert [user.id for user in response] == [UUID(int=1)]


def test_update_user_changes_department_and_status(monkeypatch):
    accounting = _make_department(1, "Accounting")
    hr = _make_department(2, "Human Resources")
    FakeDepartmentRepository.departments = {1: accounting, 2: hr}

    user = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", accounting, 1)
    FakeUserRepository.users = {user.id: user}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(user_service, "DepartmentRepository", FakeDepartmentRepository)
    monkeypatch.setattr(
        user_service,
        "UserEmploymentMovementRepository",
        FakeUserEmploymentMovementRepository,
    )

    response = anyio.run(
        _update_user,
        user.id,
        UserUpdateRequest(
            first_name="Alicia",
            department_id=2,
            is_active=False,
            assignment_effective_from=date(2026, 1, 1),
        ),
    )

    assert response.first_name == "Alicia"
    assert response.department_id == 2
    assert response.is_active is False


def test_update_user_creates_position_assignment_history(monkeypatch):
    accounting = _make_department(1, "Accounting")
    FakeDepartmentRepository.departments = {1: accounting}
    FakePositionRepository.positions = {1: _make_position(1, "OPS")}

    user = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", accounting, 1)
    FakeUserRepository.users = {user.id: user}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(user_service, "DepartmentRepository", FakeDepartmentRepository)
    monkeypatch.setattr(user_service, "PositionRepository", FakePositionRepository)
    monkeypatch.setattr(
        user_service,
        "UserPositionAssignmentRepository",
        FakeUserPositionAssignmentRepository,
    )
    monkeypatch.setattr(
        user_service,
        "UserSalaryAssignmentRepository",
        FakeUserSalaryAssignmentRepository,
    )
    monkeypatch.setattr(
        user_service,
        "UserEmploymentMovementRepository",
        FakeUserEmploymentMovementRepository,
    )

    response = anyio.run(
        _update_user,
        user.id,
        UserUpdateRequest(
            position_id=1,
            monthly_salary=Decimal("25000.00"),
            assignment_effective_from=date(2026, 1, 1),
        ),
    )

    assert response.position_id == 1
    assert response.monthly_salary == Decimal("25000.00")
    assert len(FakeUserPositionAssignmentRepository.items) == 1
    assignment = next(iter(FakeUserPositionAssignmentRepository.items.values()))
    assert assignment.changed_by == UUID(int=99)
    assert len(FakeUserSalaryAssignmentRepository.items) == 1
    salary_assignment = next(iter(FakeUserSalaryAssignmentRepository.items.values()))
    assert salary_assignment.monthly_salary == Decimal("25000.00")
    assert salary_assignment.changed_by == UUID(int=99)

    movement_fields = [movement.field_name for movement in FakeUserEmploymentMovementRepository.items]
    assert movement_fields == ["monthly_salary", "position_id"]
    assert all(movement.changed_by == UUID(int=99) for movement in FakeUserEmploymentMovementRepository.items)


def test_update_user_missing_department_raises(monkeypatch):
    user = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", None, None)
    FakeUserRepository.users = {user.id: user}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(user_service, "DepartmentRepository", FakeDepartmentRepository)

    try:
        anyio.run(
            _update_user,
            user.id,
            UserUpdateRequest(department_id=999, assignment_effective_from=date(2026, 1, 1)),
        )
    except NotFoundError as exc:
        assert exc.detail == "Department not found."
    else:
        raise AssertionError("Expected NotFoundError to be raised")


def test_update_user_employment_change_requires_effective_date(monkeypatch):
    accounting = _make_department(1, "Accounting")
    hr = _make_department(2, "Human Resources")
    FakeDepartmentRepository.departments = {1: accounting, 2: hr}

    user = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", accounting, 1)
    FakeUserRepository.users = {user.id: user}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(user_service, "DepartmentRepository", FakeDepartmentRepository)

    try:
        anyio.run(
            _update_user,
            user.id,
            UserUpdateRequest(department_id=2),
        )
    except ConflictError as exc:
        assert (
            exc.detail
            == "Assignment effective date is required when updating employment details."
        )
    else:
        raise AssertionError("Expected ConflictError to be raised")


def test_user_update_request_accepts_direct_salary_and_rejects_negative_salary():
    payload = UserUpdateRequest(monthly_salary=Decimal("25000.50"))
    assert payload.monthly_salary == Decimal("25000.50")

    try:
        UserUpdateRequest(monthly_salary=Decimal("-1.00"))
        raise AssertionError("Expected ValidationError for negative salary.")
    except ValidationError:
        pass


def test_user_update_request_normalizes_employee_fields():
    payload = UserUpdateRequest(
        employee_type="manager",
        employment_status="regular",
    )

    assert payload.employee_type == "MANAGER"
    assert payload.employment_status == "REGULAR"


def test_toggle_user_status_flips_active_flag(monkeypatch):
    user = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", None, None, is_active=True)
    FakeUserRepository.users = {user.id: user}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(user_service, "DepartmentRepository", FakeDepartmentRepository)

    response = anyio.run(_toggle_user, user.id)

    assert response.is_active is False


def test_update_user_biometric_uid(monkeypatch):
    user = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", None, None)
    FakeUserRepository.users = {user.id: user}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(user_service, "DepartmentRepository", FakeDepartmentRepository)

    response = anyio.run(
        _update_biometric,
        user.id,
        UserBiometricUpdateRequest(biometric_uid=99),
    )

    assert response.biometric_uid == 99


def test_update_user_biometric_uid_rejects_duplicates(monkeypatch):
    first = _make_user(UUID(int=1), "Alice", "A", "alice@example.com", None, None)
    second = _make_user(UUID(int=2), "Bob", "B", "bob@example.com", None, None)
    first.biometric_uid = 99
    FakeUserRepository.users = {first.id: first, second.id: second}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(user_service, "DepartmentRepository", FakeDepartmentRepository)

    try:
        anyio.run(_update_biometric, second.id, UserBiometricUpdateRequest(biometric_uid=99))
    except NotFoundError as exc:
        assert exc.detail == "Biometric UID is already assigned to another user."
    else:
        raise AssertionError("Expected NotFoundError to be raised")
