import anyio
from typing import cast
from uuid import UUID

from fastapi import BackgroundTasks, Request
from pydantic import ValidationError
from app.api.routes import auth as auth_routes
from app.core.security import decode_access_token
from app.core.time import utc_now
from app.models.user import User
from app.schemas.auth import AuthLoginRequest, AuthRegisterRequest
from app.schemas.auth import AuthResponse
from app.schemas.user import UserRead, UserWithCapabilitiesRead
from sqlalchemy.ext.asyncio import AsyncSession


class FakeUserRepository:
    users_by_email: dict[str, User] = {}
    users_by_username: dict[str, User] = {}
    users_by_id: dict[UUID, User] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def get_by_email(self, email: str):
        return self.users_by_email.get(email)

    async def get_by_username(self, username: str):
        return self.users_by_username.get(username)

    async def get_by_login_identifier(self, identifier: str):
        normalized = identifier.strip().lower()
        user = self.users_by_email.get(normalized)
        if user is not None:
            return user
        return self.users_by_username.get(normalized)

    async def get_auth_user_by_login_identifier(self, identifier: str):
        return await self.get_by_login_identifier(identifier)

    async def get_by_id(self, user_id: UUID):
        return self.users_by_id.get(user_id)

    async def create(self, user: User):
        user.id = UUID(int=self.next_id)
        self.next_id += 1
        user.created_at = user.created_at or utc_now()
        user.updated_at = user.updated_at or utc_now()
        self.users_by_email[user.email] = user
        if user.username:
            self.users_by_username[user.username] = user
        self.users_by_id[user.id] = user
        return user


async def _register(payload: dict[str, str]) -> UserRead:
    return await auth_routes.register(
        AuthRegisterRequest(**payload),
        session=cast(AsyncSession, object()),
    )


async def _login(payload: dict[str, str]) -> AuthResponse:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return await auth_routes.login(
        Request({"type": "http", "headers": []}, receive),
        BackgroundTasks(),
        AuthLoginRequest(**payload),
        session=cast(AsyncSession, object()),
    )


async def _me(user: User) -> UserWithCapabilitiesRead:
    return await auth_routes.me(current_user=user)


def test_register_returns_created_user(monkeypatch):
    FakeUserRepository.users_by_email = {}
    FakeUserRepository.users_by_username = {}
    FakeUserRepository.users_by_id = {}
    FakeUserRepository.next_id = 1

    monkeypatch.setattr(auth_routes, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(auth_routes, "hash_password", lambda password: "hashed")

    async def fake_create_app_log(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_routes, "create_app_log", fake_create_app_log)

    payload = {
        "email": "new.user@example.com",
        "username": "new.user",
        "password": "supersecret1",
        "first_name": "New",
        "last_name": "User",
        "employee_number": "EMP-001",
        "role": "EMP",
    }

    response = anyio.run(_register, payload)

    assert response.email == payload["email"]
    assert response.employee_number == payload["employee_number"]
    assert response.role == payload["role"]


def test_register_requires_username(monkeypatch):
    FakeUserRepository.users_by_email = {}
    FakeUserRepository.users_by_username = {}
    FakeUserRepository.users_by_id = {}
    FakeUserRepository.next_id = 1

    monkeypatch.setattr(auth_routes, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(auth_routes, "hash_password", lambda password: "hashed")

    payload = {
        "email": "new.user@example.com",
        "password": "supersecret1",
        "first_name": "New",
        "last_name": "User",
    }

    try:
        anyio.run(_register, payload)
        raise AssertionError("Expected ValidationError when username is missing.")
    except ValidationError:
        pass


def test_login_returns_token_and_user(monkeypatch):
    user = User(
        id=UUID(int=7),
        email="jane.doe@example.com",
        password_hash="hashed",
        first_name="Jane",
        last_name="Doe",
        can_modify_shift=False,
        is_active=True,
        is_superuser=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    FakeUserRepository.users_by_email = {user.email: user}
    FakeUserRepository.users_by_username = {}
    FakeUserRepository.users_by_id = {user.id: user}
    FakeUserRepository.next_id = 8

    monkeypatch.setattr(auth_routes, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(
        auth_routes,
        "verify_password",
        lambda password, password_hash: password == "secret-password",
    )

    response = anyio.run(
        _login,
        {"identifier": user.email, "password": "secret-password"},
    )

    assert response.token_type == "bearer"
    assert response.user.email == user.email
    assert "view_dashboard_home" in response.user.capabilities
    assert "access_hr_workspace" not in response.user.capabilities
    assert decode_access_token(response.access_token)["sub"] == str(user.id)


def test_login_accepts_username_identifier(monkeypatch):
    user = User(
        id=UUID(int=9),
        email="john.doe@example.com",
        username="john.doe",
        password_hash="hashed",
        first_name="John",
        last_name="Doe",
        can_modify_shift=False,
        is_active=True,
        is_superuser=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    FakeUserRepository.users_by_email = {user.email: user}
    FakeUserRepository.users_by_username = {"john.doe": user}
    FakeUserRepository.users_by_id = {user.id: user}
    FakeUserRepository.next_id = 10

    monkeypatch.setattr(auth_routes, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(
        auth_routes,
        "verify_password",
        lambda password, password_hash: password == "secret-password",
    )

    response = anyio.run(
        _login,
        {"identifier": "john.doe", "password": "secret-password"},
    )

    assert response.user.id == user.id


def test_me_returns_current_user_with_capabilities():
    user = User(
        id=UUID(int=11),
        email="current.user@example.com",
        password_hash="hashed",
        first_name="Current",
        last_name="User",
        can_modify_shift=False,
        is_active=True,
        is_superuser=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    response = anyio.run(_me, user)

    assert response.email == user.email
    assert "view_dashboard_home" in response.capabilities
    assert "access_hr_workspace" not in response.capabilities


def test_me_includes_hr_workspace_capability_for_hr_user():
    user = User(
        id=UUID(int=12),
        email="hr.user@example.com",
        password_hash="hashed",
        first_name="HR",
        last_name="User",
        role="HR",
        can_modify_shift=False,
        is_active=True,
        is_superuser=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    response = anyio.run(_me, user)

    assert response.email == user.email
    assert "access_hr_workspace" in response.capabilities
