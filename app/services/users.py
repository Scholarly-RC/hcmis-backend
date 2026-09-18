from uuid import UUID, uuid4

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.core.exceptions import NotFoundError
from app.core.security import generate_temporary_password, hash_password
from app.models.user import User, UserEmploymentMovement, UserPositionAssignment, UserSalaryAssignment
from app.repositories.departments import DepartmentRepository
from app.repositories.payroll import PositionRepository
from app.repositories.users import UserRepository
from app.repositories.users import UserEmploymentMovementRepository
from app.repositories.users import UserPositionAssignmentRepository
from app.repositories.users import UserSalaryAssignmentRepository
from app.schemas.user import UserCreateRequest
from app.schemas.user import (
    UserBiometricUpdateRequest,
    UserProfileUpdateRequest,
    UserUpdateRequest,
)
from app.services.notifications import create_notification_if_possible
from app.services.profile_photo_storage import (
    delete_profile_photo_by_url,
    save_profile_photo,
)
from app.core.time import local_today


EMPLOYMENT_MOVEMENT_FIELDS = {
    "position_id",
    "monthly_salary",
    "department_id",
    "employee_type",
    "employment_status",
    "date_of_hiring",
    "resignation_date",
}


def _normalize_username(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "":
        return None
    return normalized


def _default_assignment_effective_from(
    assignment_effective_from: date | None,
    date_of_hiring: date | None,
) -> date:
    if assignment_effective_from is not None:
        return assignment_effective_from
    if date_of_hiring is not None:
        return date_of_hiring
    return local_today()


async def _validate_position(
    session: AsyncSession,
    position_id: int | None,
) -> int | None:
    if position_id is None:
        return None
    position = await PositionRepository(session).get_by_id(position_id)
    if position is None:
        raise NotFoundError("Position not found.")
    return position_id


async def _validate_user_approver_assignments(
    *,
    user_repository: UserRepository,
    target_user_id: UUID | None,
    level_1_approver_id: UUID | None,
    level_2_approver_id: UUID | None,
) -> tuple[UUID | None, UUID | None]:
    if (
        level_1_approver_id is not None
        and level_2_approver_id is not None
        and level_1_approver_id == level_2_approver_id
    ):
        raise ConflictError("Level 1 and Level 2 approvers must be different users.")

    for approver_id, label in (
        (level_1_approver_id, "Level 1 approver"),
        (level_2_approver_id, "Level 2 approver"),
    ):
        if approver_id is None:
            continue
        approver = await user_repository.get_by_id(approver_id)
        if approver is None:
            raise NotFoundError(f"{label} user not found.")
        if not approver.is_active:
            raise ConflictError(f"{label} must be an active user.")
        if target_user_id is not None and approver.id == target_user_id:
            raise ConflictError(f"{label} cannot be the same as the selected user.")

    return level_1_approver_id, level_2_approver_id


async def _upsert_current_position_assignment(
    session: AsyncSession,
    user: User,
    *,
    position_id: int,
    effective_from: date,
    change_reason: str | None,
    changed_by: UUID | None,
) -> None:
    assignment_repository = UserPositionAssignmentRepository(session)
    active_assignment = await assignment_repository.get_active_for_user_on(user.id, effective_from)
    if (
        active_assignment is not None
        and active_assignment.position_id == position_id
        and active_assignment.effective_from == effective_from
    ):
        return
    overlapping = await assignment_repository.get_overlapping_assignments(
        user.id,
        effective_from,
        None,
    )
    for assignment in overlapping:
        if assignment.effective_to is None or assignment.effective_to >= effective_from:
            assignment.effective_to = effective_from
            if assignment.effective_to is not None:
                assignment.effective_to = assignment.effective_to - timedelta(days=1)
            await assignment_repository.save(assignment)
    await assignment_repository.create(
        UserPositionAssignment(
            user_id=user.id,
            position_id=position_id,
            effective_from=effective_from,
            effective_to=None,
            change_reason=change_reason,
            changed_by=changed_by,
        )
    )


async def _upsert_current_salary_assignment(
    session: AsyncSession,
    user: User,
    *,
    monthly_salary: Decimal | None,
    effective_from: date,
    change_reason: str | None,
    changed_by: UUID | None,
) -> None:
    assignment_repository = UserSalaryAssignmentRepository(session)
    overlapping = await assignment_repository.get_overlapping_assignments(
        user.id,
        effective_from,
        None,
    )
    for assignment in overlapping:
        if assignment.effective_to is None or assignment.effective_to >= effective_from:
            assignment.effective_to = effective_from - timedelta(days=1)
            await assignment_repository.save(assignment)
    if monthly_salary is None:
        return
    await assignment_repository.create(
        UserSalaryAssignment(
            user_id=user.id,
            monthly_salary=monthly_salary,
            effective_from=effective_from,
            effective_to=None,
            change_reason=change_reason,
            changed_by=changed_by,
        )
    )


async def list_users(
    session: AsyncSession,
    query: str | None = None,
    department_id: int | None = None,
    active_only: bool | None = None,
    include_superusers: bool = False,
    exclude_hr: bool = False,
    exclude_user_id: UUID | None = None,
) -> list[User]:
    repository = UserRepository(session)
    return await repository.list(
        query=query,
        department_id=department_id,
        active_only=active_only,
        include_superusers=include_superusers,
        exclude_hr=exclude_hr,
        exclude_user_id=exclude_user_id,
    )


async def create_user(
    session: AsyncSession,
    payload: UserCreateRequest,
    *,
    actor_user_id: UUID | None = None,
) -> User:
    user_repository = UserRepository(session)
    department_repository = DepartmentRepository(session)
    email = payload.email.lower()
    username = _normalize_username(payload.username)
    if username is None:
        raise ValueError("Username is required.")

    existing_user = await user_repository.get_by_email(email)
    if existing_user is not None:
        raise ConflictError("Email is already registered.")
    existing_username = await user_repository.get_by_username(username)
    if existing_username is not None:
        raise ConflictError("Username is already registered.")

    if payload.employee_number:
        existing_employee = await user_repository.get_by_employee_number(
            payload.employee_number
        )
        if existing_employee is not None:
            raise ConflictError("Employee number already exists.")

    if payload.biometric_uid is not None:
        existing_biometric = await user_repository.get_by_biometric_uid(
            payload.biometric_uid
        )
        if existing_biometric is not None:
            raise ConflictError("Biometric UID is already assigned to another user.")

    if payload.department_id is not None:
        department = await department_repository.get_by_id(payload.department_id)
        if department is None:
            raise NotFoundError("Department not found.")

    level_1_approver_id, level_2_approver_id = await _validate_user_approver_assignments(
        user_repository=user_repository,
        target_user_id=None,
        level_1_approver_id=payload.level_1_approver_id,
        level_2_approver_id=payload.level_2_approver_id,
    )

    position_id = await _validate_position(session, payload.position_id)

    password_hash = hash_password(payload.password)
    user = User(
        email=email,
        username=username,
        password_hash=password_hash,
        first_name=payload.first_name,
        last_name=payload.last_name,
        middle_name=payload.middle_name,
        gender=payload.gender,
        highest_education_level=payload.highest_education_level,
        highest_education_program=payload.highest_education_program,
        civil_status=payload.civil_status,
        religion=payload.religion,
        position_id=position_id,
        monthly_salary=payload.monthly_salary,
        employee_number=payload.employee_number,
        biometric_uid=payload.biometric_uid,
        role=payload.role,
        employee_type=payload.employee_type,
        employment_status=payload.employment_status,
        department_id=payload.department_id,
        level_1_approver_id=level_1_approver_id,
        level_2_approver_id=level_2_approver_id,
        phone_number=payload.phone_number,
        address=payload.address,
        date_of_birth=payload.date_of_birth,
        date_of_hiring=payload.date_of_hiring,
        resignation_date=payload.resignation_date,
        profile_picture_url=payload.profile_picture_url,
        can_modify_shift=payload.can_modify_shift,
        is_active=payload.is_active,
        is_superuser=payload.is_superuser,
    )
    try:
        created_user = await user_repository.create(user)
    except IntegrityError as exc:
        raise ConflictError("User already exists.") from exc
    effective_from = _default_assignment_effective_from(
        payload.assignment_effective_from,
        payload.date_of_hiring,
    )
    if position_id is not None:
        await _upsert_current_position_assignment(
            session,
            created_user,
            position_id=position_id,
            effective_from=effective_from,
            change_reason=payload.assignment_change_reason,
            changed_by=actor_user_id,
        )
    if payload.monthly_salary is not None:
        await _upsert_current_salary_assignment(
            session,
            created_user,
            monthly_salary=payload.monthly_salary,
            effective_from=effective_from,
            change_reason=payload.assignment_change_reason,
            changed_by=actor_user_id,
        )
    if position_id is not None or payload.monthly_salary is not None:
        created_user = await user_repository.get_by_id(created_user.id) or created_user
    return created_user


async def get_user(session: AsyncSession, user_id: UUID) -> User:
    repository = UserRepository(session)
    user = await repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")
    return user


async def list_user_employment_movements(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int = 100,
) -> list[UserEmploymentMovement]:
    await get_user(session, user_id)
    repository = UserEmploymentMovementRepository(session)
    return await repository.list_for_user(user_id, limit=limit)


async def update_user(
    session: AsyncSession,
    user_id: UUID,
    payload: UserUpdateRequest,
    *,
    actor_user_id: UUID | None = None,
) -> User:
    user_repository = UserRepository(session)
    department_repository = DepartmentRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    data = payload.model_dump(exclude_unset=True)
    username = _normalize_username(data.pop("username", user.username))
    department_id = data.pop("department_id", None) if "department_id" in data else None
    level_1_approver_id = (
        data.pop("level_1_approver_id", user.level_1_approver_id)
        if "level_1_approver_id" in data
        else user.level_1_approver_id
    )
    level_2_approver_id = (
        data.pop("level_2_approver_id", user.level_2_approver_id)
        if "level_2_approver_id" in data
        else user.level_2_approver_id
    )
    position_id = data.pop("position_id", user.position_id) if "position_id" in data else user.position_id
    monthly_salary = (
        data.pop("monthly_salary", user.monthly_salary)
        if "monthly_salary" in data
        else user.monthly_salary
    )
    assignment_effective_from = data.pop("assignment_effective_from", None)
    assignment_change_reason = data.pop("assignment_change_reason", None)
    proposed_employment_values = {
        "position_id": position_id,
        "monthly_salary": monthly_salary,
        "department_id": department_id if "department_id" in payload.model_fields_set else user.department_id,
        "employee_type": data.get("employee_type", user.employee_type),
        "employment_status": data.get("employment_status", user.employment_status),
        "date_of_hiring": data.get("date_of_hiring", user.date_of_hiring),
        "resignation_date": data.get("resignation_date", user.resignation_date),
    }
    has_employment_value_change = any(
        getattr(user, field_name) != proposed_value
        for field_name, proposed_value in proposed_employment_values.items()
    )
    if has_employment_value_change and assignment_effective_from is None:
        raise ConflictError(
            "Assignment effective date is required when updating employment details."
        )
    if "department_id" in payload.model_fields_set:
        if department_id is None:
            user.department_id = None
        else:
            department = await department_repository.get_by_id(department_id)
            if department is None:
                raise NotFoundError("Department not found.")
            user.department_id = department.id

    level_1_approver_id, level_2_approver_id = await _validate_user_approver_assignments(
        user_repository=user_repository,
        target_user_id=user.id,
        level_1_approver_id=level_1_approver_id,
        level_2_approver_id=level_2_approver_id,
    )

    position_id = await _validate_position(session, position_id)

    original_values = {
        field_name: getattr(user, field_name, None) for field_name in EMPLOYMENT_MOVEMENT_FIELDS
    }

    for field_name, value in data.items():
        setattr(user, field_name, value)
    if username != user.username:
        if username is not None:
            existing_username = await user_repository.get_by_username(username)
            if existing_username is not None and existing_username.id != user.id:
                raise ConflictError("Username is already registered.")
        user.username = username
    user.level_1_approver_id = level_1_approver_id
    user.level_2_approver_id = level_2_approver_id

    assignment_changed = position_id != user.position_id
    salary_changed = monthly_salary != user.monthly_salary
    user.position_id = position_id
    user.monthly_salary = monthly_salary

    saved_user = await user_repository.save(user)
    changed_fields = [
        field_name
        for field_name in EMPLOYMENT_MOVEMENT_FIELDS
        if original_values.get(field_name) != getattr(saved_user, field_name, None)
    ]
    if changed_fields:
        movement_repository = UserEmploymentMovementRepository(session)
        change_batch_id = uuid4()
        movements = [
            UserEmploymentMovement(
                user_id=saved_user.id,
                field_name=field_name,
                old_value=(
                    str(original_values.get(field_name))
                    if original_values.get(field_name) is not None
                    else None
                ),
                new_value=(
                    str(getattr(saved_user, field_name, None))
                    if getattr(saved_user, field_name, None) is not None
                    else None
                ),
                change_batch_id=change_batch_id,
                changed_by=actor_user_id,
                effective_date=assignment_effective_from,
            )
            for field_name in sorted(changed_fields)
        ]
        await movement_repository.create_many(movements)
    effective_from = _default_assignment_effective_from(
        assignment_effective_from,
        saved_user.date_of_hiring,
    )
    if position_id is not None and assignment_changed:
        await _upsert_current_position_assignment(
            session,
            saved_user,
            position_id=position_id,
            effective_from=effective_from,
            change_reason=assignment_change_reason,
            changed_by=actor_user_id,
        )
    if salary_changed:
        await _upsert_current_salary_assignment(
            session,
            saved_user,
            monthly_salary=monthly_salary,
            effective_from=effective_from,
            change_reason=assignment_change_reason,
            changed_by=actor_user_id,
        )
    if assignment_changed or salary_changed:
        saved_user = await user_repository.get_by_id(saved_user.id) or saved_user
    return saved_user


async def toggle_user_status(session: AsyncSession, user_id: UUID) -> User:
    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    user.is_active = not user.is_active
    user = await user_repository.save(user)
    status_text = "activated" if user.is_active else "deactivated"
    await create_notification_if_possible(
        session,
        recipient_id=user.id,
        content=f"Your account was {status_text}.",
        url="/profile",
    )
    return user


async def update_own_profile(
    session: AsyncSession, user_id: UUID, payload: UserProfileUpdateRequest
) -> User:
    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    data = payload.model_dump(exclude_unset=True)
    for field_name, value in data.items():
        setattr(user, field_name, value)

    return await user_repository.save(user)


async def upload_own_profile_photo(
    session: AsyncSession,
    user_id: UUID,
    uploaded_file: UploadFile,
) -> User:
    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    previous_photo_url = user.profile_picture_url
    stored_photo = await save_profile_photo(
        user_id=user_id,
        uploaded_file=uploaded_file,
    )
    user.profile_picture_url = stored_photo.url

    try:
        saved_user = await user_repository.save(user)
    except Exception:
        delete_profile_photo_by_url(stored_photo.url)
        raise

    if previous_photo_url and previous_photo_url != stored_photo.url:
        delete_profile_photo_by_url(previous_photo_url)

    return saved_user


async def update_user_biometric_uid(
    session: AsyncSession, user_id: UUID, payload: UserBiometricUpdateRequest
) -> User:
    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    if payload.biometric_uid is None:
        user.biometric_uid = None
        return await user_repository.save(user)

    users = await user_repository.list(include_superusers=True)
    for other_user in users:
        if other_user.id != user_id and other_user.biometric_uid == payload.biometric_uid:
            raise NotFoundError("Biometric UID is already assigned to another user.")

    user.biometric_uid = payload.biometric_uid
    return await user_repository.save(user)


async def reset_user_password(
    session: AsyncSession,
    user_id: UUID,
) -> tuple[User, str]:
    user_repository = UserRepository(session)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    temporary_password = generate_temporary_password()
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.temporary_password_expires_at = datetime.now(UTC) + timedelta(hours=24)
    saved_user = await user_repository.save(user)
    await create_notification_if_possible(
        session,
        recipient_id=saved_user.id,
        content="Your password was reset by HR. Please change it on your next login.",
        url="/change-password",
    )
    return saved_user, temporary_password
