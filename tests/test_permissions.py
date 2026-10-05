import anyio
import pytest

from fastapi import HTTPException

from app.api import deps as api_deps
from app.api.routes.users import ensure_hr_can_modify_employment_fields
from app.core.capabilities import resolve_user_capabilities
from app.core.time import utc_now
from app.models.user import User


async def _require_staff(user: User):
    return await api_deps.require_staff_user(current_user=user)


async def _require_hr(user: User):
    return await api_deps.require_hr_user(current_user=user)


def _make_user(
    user_id: int,
    role: str | None,
    *,
    is_superuser: bool = False,
    can_modify_shift: bool = False,
) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@example.com",
        password_hash="hashed",
        first_name="Test",
        last_name="User",
        role=role,
        can_modify_shift=can_modify_shift,
        is_active=True,
        is_superuser=is_superuser,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_require_staff_user_denies_employee():
    employee = _make_user(1, "EMP")

    with pytest.raises(HTTPException) as exc:
        anyio.run(_require_staff, employee)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Not enough permissions."


def test_require_staff_user_allows_hr():
    hr_user = _make_user(2, "HR")

    result = anyio.run(_require_staff, hr_user)

    assert result.id == hr_user.id


def test_require_staff_user_allows_superuser():
    superuser = _make_user(3, "EMP", is_superuser=True)

    result = anyio.run(_require_staff, superuser)

    assert result.id == superuser.id


def test_require_hr_user_denies_non_hr_superuser():
    superuser = _make_user(9, "EMP", is_superuser=True)

    with pytest.raises(HTTPException) as exc:
        anyio.run(_require_hr, superuser)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Only HR users can access this report."


def test_require_hr_user_allows_hr_superuser():
    hr_superuser = _make_user(10, "HR", is_superuser=True)

    result = anyio.run(_require_hr, hr_superuser)

    assert result.id == hr_superuser.id


def test_capability_resolution_for_employee():
    employee = _make_user(4, "EMP")

    capabilities = resolve_user_capabilities(employee)

    assert "view_dashboard_home" in capabilities
    assert "access_hr_workspace" not in capabilities
    assert "manage_hr_users" not in capabilities


def test_capability_resolution_for_hr():
    hr_user = _make_user(5, "HR")

    capabilities = resolve_user_capabilities(hr_user)

    assert "access_hr_workspace" in capabilities
    assert "manage_hr_users" in capabilities
    assert "view_reports" in capabilities
    assert "view_payroll_summary" in capabilities


def test_capability_resolution_for_superuser():
    superuser = _make_user(6, "EMP", is_superuser=True, can_modify_shift=True)

    capabilities = resolve_user_capabilities(superuser)

    assert "access_hr_workspace" in capabilities
    assert "manage_shift_templates" in capabilities
    assert "view_app_logs" in capabilities
    assert "view_payroll_summary" not in capabilities


def test_non_hr_cannot_modify_employee_type_or_employment_status():
    superuser = _make_user(7, "EMP", is_superuser=True)

    with pytest.raises(HTTPException) as exc:
        ensure_hr_can_modify_employment_fields(
            current_user=superuser,
            fields_set={"employee_type"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Only HR can modify employee type and employment status."


def test_hr_can_modify_employee_type_or_employment_status():
    hr_user = _make_user(8, "HR")

    ensure_hr_can_modify_employment_fields(
        current_user=hr_user,
        fields_set={"employment_status"},
    )
