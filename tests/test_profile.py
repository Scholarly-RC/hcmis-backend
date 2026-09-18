import anyio
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.models.user import User
from app.schemas.user import UserProfileUpdateRequest
from app.services import users as user_service


class FakeUserRepository:
    users: dict[UUID, User] = {}

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, user_id: UUID):
        return self.users.get(user_id)

    async def save(self, user: User):
        user.updated_at = utc_now()
        self.users[user.id] = user
        return user


async def _get_profile(user: User):
    return user


async def _update_profile(user_id: UUID, payload: UserProfileUpdateRequest):
    return await user_service.update_own_profile(
        session=cast(AsyncSession, object()),
        user_id=user_id,
        payload=payload,
    )


def setup_function():
    FakeUserRepository.users = {}


def _make_user():
    return User(
        id=UUID(int=1),
        email="current.user@example.com",
        password_hash="hashed",
        first_name="Current",
        last_name="User",
        middle_name=None,
        gender=None,
        highest_education_level=None,
        highest_education_program=None,
        civil_status=None,
        religion=None,
        employee_number=None,
        role=None,
        department_id=None,
        phone_number=None,
        address=None,
        date_of_birth=None,
        date_of_hiring=None,
        resignation_date=None,
        profile_picture_url=None,
        can_modify_shift=False,
        is_active=True,
        is_superuser=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_get_profile_returns_current_user():
    user = _make_user()
    response = anyio.run(_get_profile, user)

    assert response.email == user.email


def test_update_profile_updates_allowed_fields(monkeypatch):
    user = _make_user()
    FakeUserRepository.users = {user.id: user}

    monkeypatch.setattr(user_service, "UserRepository", FakeUserRepository)

    response = anyio.run(
        _update_profile,
        user.id,
        UserProfileUpdateRequest(
            first_name="Updated",
            last_name="Person",
            phone_number="09171234567",
            gender="M",
        ),
    )

    assert response.first_name == "Updated"
    assert response.last_name == "Person"
    assert response.phone_number == "09171234567"
    assert response.gender == "M"
