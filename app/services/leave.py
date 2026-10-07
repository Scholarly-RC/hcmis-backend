import re
from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import is_staff_user
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.core.time import local_today, utc_now
from app.models.leave import (
    LeaveCredit,
    LeaveRequest,
    LeaveRequestApprover,
    LeaveRequestStatus,
    LeaveType,
    LeaveTypePolicy,
)
from app.models.attendance import OvertimeRequest
from app.repositories.attendance import OvertimeRepository
from app.models.user import User
from app.repositories.leave import (
    LeaveCreditRepository,
    LeaveRequestRepository,
    LeaveTypeRepository,
)
from app.repositories.users import UserRepository
from app.services.notifications import create_notification
from app.schemas.leave import (
    LeaveCreditUpsertRequest,
    LeaveRequestCreateRequest,
    LeaveRequestReviewRequest,
    LeaveTypePolicyUpsertRequest,
)

MONTHLY_INCREMENTAL_CREDITS = 1.25


def _leave_duration_units(duration: str | None) -> float:
    return 0.5 if duration in {"FIRST_HALF", "SECOND_HALF"} else 1.0


class LeaveCreditSnapshot(TypedDict):
    user_id: UUID
    leave_type: str
    credits: float
    used_credits: float
    remaining_credits: float
    user: User
    created_at: None
    updated_at: None


def _normalize_leave_type_name(name: str) -> str:
    return " ".join(name.strip().split())


def _build_leave_type_code(name: str, existing_codes: set[str]) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not normalized:
        normalized = "leave_type"
    base = normalized[:24]
    candidate = base
    suffix = 2
    while candidate in existing_codes:
        suffix_text = f"_{suffix}"
        candidate = f"{base[: max(1, 24 - len(suffix_text))]}{suffix_text}"
        suffix += 1
    return candidate


def _to_leave_type_option(leave_type: LeaveTypePolicy) -> dict[str, str]:
    return {"value": leave_type.code, "label": leave_type.name}


async def list_leave_types(session: AsyncSession) -> list[dict[str, str]]:
    leave_types = await LeaveTypeRepository(session).list()
    return [_to_leave_type_option(item) for item in leave_types]


async def list_leave_type_policies(session: AsyncSession) -> list[LeaveTypePolicy]:
    return await LeaveTypeRepository(session).list()


async def create_leave_type_policy(
    session: AsyncSession,
    payload: LeaveTypePolicyUpsertRequest,
) -> LeaveTypePolicy:
    repository = LeaveTypeRepository(session)
    normalized_name = _normalize_leave_type_name(payload.name)
    existing_by_name = await repository.get_by_name(normalized_name)
    if existing_by_name is not None:
        raise ConflictError("A leave type with this name already exists.")

    existing_codes = {item.code for item in await repository.list()}
    code = _build_leave_type_code(normalized_name, existing_codes)
    leave_type = LeaveTypePolicy(
        code=code,
        name=normalized_name,
        max_credits=payload.max_credits,
        credit_mode=payload.credit_mode,
    )
    return await repository.create(leave_type)


async def update_leave_type_policy(
    session: AsyncSession,
    leave_type_id: UUID,
    payload: LeaveTypePolicyUpsertRequest,
) -> LeaveTypePolicy:
    repository = LeaveTypeRepository(session)
    leave_type = await repository.get_by_id(leave_type_id)
    if leave_type is None:
        raise NotFoundError("Leave type not found.")

    normalized_name = _normalize_leave_type_name(payload.name)
    existing_by_name = await repository.get_by_name(normalized_name)
    if existing_by_name is not None and existing_by_name.id != leave_type.id:
        raise ConflictError("A leave type with this name already exists.")

    leave_type.name = normalized_name
    leave_type.max_credits = payload.max_credits
    leave_type.credit_mode = payload.credit_mode
    return await repository.save(leave_type)


async def delete_leave_type_policy(session: AsyncSession, leave_type_id: UUID) -> None:
    repository = LeaveTypeRepository(session)
    leave_type = await repository.get_by_id(leave_type_id)
    if leave_type is None:
        raise NotFoundError("Leave type not found.")

    is_used = await repository.has_leave_requests_for_code(leave_type.code)
    if is_used:
        raise ConflictError("Leave type cannot be deleted because it is already referenced.")

    await repository.delete(leave_type)


async def _ensure_leave_credit(session: AsyncSession, user_id: UUID) -> LeaveCredit:
    repository = LeaveCreditRepository(session)
    leave_credit = await repository.get_by_user_id(user_id)
    if leave_credit is None:
        leave_credit = LeaveCredit(user_id=user_id, credits=0, used_credits=0)
        return await repository.create(leave_credit)
    return leave_credit


def _completed_months_since_hire(hire_date: date | None, as_of: date) -> int:
    if hire_date is None or as_of < hire_date:
        return 0
    months = (as_of.year - hire_date.year) * 12 + (as_of.month - hire_date.month)
    if as_of.day < hire_date.day:
        months -= 1
    return max(months, 0)


def _build_anniversary_date(*, year: int, month: int, day: int) -> date:
    valid_day = min(day, monthrange(year, month)[1])
    return date(year, month, valid_day)


def _credit_cycle_start(user: User, as_of: date) -> date:
    hire_date = user.date_of_hiring
    if hire_date is None:
        return date(as_of.year, 1, 1)

    this_year_anniversary = _build_anniversary_date(
        year=as_of.year,
        month=hire_date.month,
        day=hire_date.day,
    )
    if as_of >= this_year_anniversary:
        return this_year_anniversary

    return _build_anniversary_date(
        year=as_of.year - 1,
        month=hire_date.month,
        day=hire_date.day,
    )


def _calculate_total_credits(user: User, leave_type_policy: LeaveTypePolicy, as_of: date) -> float:
    if user.date_of_hiring is None:
        return 0.0

    if leave_type_policy.credit_mode == "fixed":
        return float(leave_type_policy.max_credits)

    cycle_start = _credit_cycle_start(user, as_of)
    months_completed = _completed_months_since_hire(cycle_start, as_of)
    accrued = months_completed * MONTHLY_INCREMENTAL_CREDITS
    return min(float(leave_type_policy.max_credits), accrued)


async def _resolve_leave_type_policy(
    session: AsyncSession, leave_type: str | None
) -> LeaveTypePolicy:
    repository = LeaveTypeRepository(session)
    if leave_type is not None:
        selected = await repository.get_by_code(leave_type)
        if selected is None:
            raise NotFoundError("Leave type not found.")
        return selected

    leave_types = await repository.list()
    if not leave_types:
        raise NotFoundError("No leave types configured.")

    paid = next((item for item in leave_types if item.code == LeaveType.PAID.value), None)
    return paid or leave_types[0]


async def _get_approval_pool(session: AsyncSession, user: User) -> list[UUID]:
    if user.level_1_approver_id is None:
        raise NotFoundError("No Level 1 approver is configured for this user.")
    user_repository = UserRepository(session)
    primary_approver = await user_repository.get_by_id(user.level_1_approver_id)
    if primary_approver is None or not primary_approver.is_active:
        raise NotFoundError("Level 1 approver is not available for this user.")
    if primary_approver.id == user.id:
        raise ConflictError("Level 1 approver cannot be the same as the requester.")
    return [primary_approver.id]


async def _get_backup_approver_id(session: AsyncSession, user: User) -> UUID | None:
    if user.level_2_approver_id is not None:
        user_repository = UserRepository(session)
        backup = await user_repository.get_by_id(user.level_2_approver_id)
        if backup is None or not backup.is_active:
            raise NotFoundError("Level 2 approver is not available for this user.")
        if backup.id == user.id:
            raise ConflictError("Level 2 approver cannot be the same as the requester.")
        if user.level_1_approver_id is not None and backup.id == user.level_1_approver_id:
            raise ConflictError("Level 2 approver must be different from Level 1 approver.")
        return backup.id

    return None


def _leave_type_label(leave_type: str) -> str:
    return leave_type


def _user_display_name(user: User) -> str:
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return full_name or user.email


async def _notify_user(
    session: AsyncSession,
    *,
    recipient_id: UUID | None,
    sender_id: UUID | None,
    content: str,
    url: str | None,
) -> None:
    if recipient_id is None:
        return
    if recipient_id == sender_id:
        return

    # Service tests use cast(object()) instead of an actual AsyncSession.
    if not hasattr(session, "add") or not hasattr(session, "commit"):
        return

    await create_notification(
        session,
        recipient_id=recipient_id,
        sender_id=sender_id,
        content=content,
        url=url,
    )


async def list_leave_requests(
    session: AsyncSession,
    user_id: UUID | None = None,
    department_id: int | None = None,
    approver_id: UUID | None = None,
    status: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> list[LeaveRequest]:
    return await LeaveRequestRepository(session).list(
        user_id=user_id,
        department_id=department_id,
        approver_id=approver_id,
        status=status,
        year=year,
        month=month,
    )


async def list_leave_years(session: AsyncSession) -> list[int]:
    return await LeaveRequestRepository(session).list_years()


async def get_leave_request(session: AsyncSession, leave_id: int) -> LeaveRequest:
    leave_request = await LeaveRequestRepository(session).get_by_id(leave_id)
    if leave_request is None:
        raise NotFoundError("Leave request not found.")
    return leave_request


async def create_leave_request(
    session: AsyncSession, current_user: User, payload: LeaveRequestCreateRequest
) -> LeaveRequest:
    active_statuses = (
        LeaveRequestStatus.PENDING.value,
        LeaveRequestStatus.APPROVED.value,
    )
    existing_leave = await LeaveRequestRepository(session).get_active_for_user_date(
        current_user.id,
        payload.leave_date,
        statuses=active_statuses,
    )
    if existing_leave is not None:
        raise ConflictError("An active leave request already exists for this date.")

    existing_overtime = await OvertimeRepository(session).get_active_for_user_date(
        current_user.id,
        payload.leave_date,
        statuses=(
            OvertimeRequest.Status.PENDING.value,
            OvertimeRequest.Status.APPROVED.value,
        ),
    )
    if existing_overtime is not None:
        raise ConflictError("An active overtime request already exists for this date.")

    approval_pool = await _get_approval_pool(session, current_user)
    first_approver_id = approval_pool[0]
    second_approver_id = await _get_backup_approver_id(session, current_user)
    leave_request = LeaveRequest(
        user_id=current_user.id,
        leave_date=payload.leave_date,
        leave_type=payload.leave_type,
        duration=payload.duration,
        info=payload.info,
        first_approver_id=first_approver_id,
        second_approver_id=second_approver_id,
        first_approver_status=LeaveRequestStatus.PENDING.value,
        second_approver_status=(
            LeaveRequestStatus.PENDING.value if second_approver_id is not None else None
        ),
        status=LeaveRequestStatus.PENDING.value,
        approver_pool=[
            LeaveRequestApprover(
                approver_id=approver_id,
                status=LeaveRequestStatus.PENDING.value,
            )
            for approver_id in approval_pool
        ],
    )
    leave_request = await LeaveRequestRepository(session).create(leave_request)

    leave_date = leave_request.leave_date.isoformat()
    requester_name = _user_display_name(current_user)
    leave_type = _leave_type_label(leave_request.leave_type)
    for approver_id in approval_pool:
        await _notify_user(
            session,
            recipient_id=approver_id,
            sender_id=current_user.id,
            content=f"{requester_name} filed a {leave_type} leave request for {leave_date}.",
            url=f"/leave/inbox?leave_id={leave_request.id}",
        )
    return leave_request


async def cancel_leave_request(
    session: AsyncSession, leave_id: int, current_user: User
) -> LeaveRequest:
    repository = LeaveRequestRepository(session)
    leave_request = await repository.get_by_id(leave_id)
    if leave_request is None:
        raise NotFoundError("Leave request not found.")

    if leave_request.user_id != current_user.id and not is_staff_user(current_user):
        raise PermissionDeniedError("You are not allowed to cancel this leave request.")
    if leave_request.status != LeaveRequestStatus.PENDING.value:
        raise ConflictError("Only pending leave requests can be cancelled.")

    now = utc_now()
    leave_request.status = LeaveRequestStatus.CANCELLED.value
    if leave_request.first_approver_status == LeaveRequestStatus.PENDING.value:
        leave_request.first_approver_status = LeaveRequestStatus.CANCELLED.value
        leave_request.first_approver_at = now
    if leave_request.second_approver_status == LeaveRequestStatus.PENDING.value:
        leave_request.second_approver_status = LeaveRequestStatus.CANCELLED.value
        leave_request.second_approver_at = now
    for assignment in leave_request.approver_pool:
        if assignment.status == LeaveRequestStatus.PENDING.value:
            assignment.status = LeaveRequestStatus.CANCELLED.value
            assignment.acted_at = now

    return await repository.save(leave_request)


async def review_leave_request(
    session: AsyncSession,
    leave_id: int,
    current_user: User,
    payload: LeaveRequestReviewRequest,
) -> LeaveRequest:
    repository = LeaveRequestRepository(session)
    leave_request = await repository.get_by_id(leave_id)
    if leave_request is None:
        raise NotFoundError("Leave request not found.")

    if leave_request.status != LeaveRequestStatus.PENDING.value:
        raise ConflictError("Leave request has already been processed.")

    response = payload.response
    now = utc_now()

    if leave_request.user_id == current_user.id:
        raise PermissionDeniedError("You cannot review your own leave request.")

    current_pool_assignment = next(
        (
            assignment
            for assignment in leave_request.approver_pool
            if assignment.approver_id == current_user.id
        ),
        None,
    )
    if current_pool_assignment is None:
        raise PermissionDeniedError("You do not have approval rights for this request.")
    if current_pool_assignment.status != LeaveRequestStatus.PENDING.value:
        raise ConflictError("Leave request has already been reviewed by you.")

    if response == "APPROVE":
        if payload.approval_type is None:
            raise ConflictError("Approval type is required for leave approval.")
        leave_request.approval_type = payload.approval_type
        if payload.approval_type == "PAID":
            leave_credit = await get_my_leave_credit(
                session,
                leave_request.user_id,
                leave_type=leave_request.leave_type,
            )
            remaining_credits = leave_credit["remaining_credits"]
            if remaining_credits < _leave_duration_units(leave_request.duration):
                raise ConflictError("Insufficient leave credits for paid leave.")

    final_status = (
        LeaveRequestStatus.APPROVED.value
        if response == "APPROVE"
        else LeaveRequestStatus.REJECTED.value
    )
    current_pool_assignment.status = final_status
    current_pool_assignment.acted_at = now
    for assignment in leave_request.approver_pool:
        if assignment is current_pool_assignment:
            continue
        if assignment.status == LeaveRequestStatus.PENDING.value:
            assignment.status = final_status

    if (
        leave_request.first_approver_id is not None
        and leave_request.first_approver_status == LeaveRequestStatus.PENDING.value
    ):
        leave_request.first_approver_status = final_status
        leave_request.first_approver_at = now
    if (
        leave_request.second_approver_id is not None
        and leave_request.second_approver_status == LeaveRequestStatus.PENDING.value
    ):
        leave_request.second_approver_status = final_status
        leave_request.second_approver_at = now
    leave_request.status = final_status

    leave_request = await repository.save(leave_request)

    leave_date = leave_request.leave_date.isoformat()
    leave_type = _leave_type_label(leave_request.leave_type)

    if response == "APPROVE":
        if leave_request.status == LeaveRequestStatus.APPROVED.value:
            await _notify_user(
                session,
                recipient_id=leave_request.user_id,
                sender_id=current_user.id,
                content=f"Your {leave_type} leave request for {leave_date} has been approved.",
                url=f"/leave?leave_id={leave_request.id}",
            )
    elif leave_request.status == LeaveRequestStatus.REJECTED.value:
        await _notify_user(
            session,
            recipient_id=leave_request.user_id,
            sender_id=current_user.id,
            content=f"Your {leave_type} leave request for {leave_date} has been rejected.",
            url=f"/leave?leave_id={leave_request.id}",
        )

    return leave_request


async def escalate_leave_request(
    session: AsyncSession,
    leave_id: int,
    current_user: User,
) -> LeaveRequest:
    repository = LeaveRequestRepository(session)
    leave_request = await repository.get_by_id(leave_id)
    if leave_request is None:
        raise NotFoundError("Leave request not found.")
    if leave_request.status != LeaveRequestStatus.PENDING.value:
        raise ConflictError("Only pending leave requests can be escalated.")
    if leave_request.escalated_to_backup_at is not None:
        raise ConflictError("Leave request is already escalated to the backup approver.")
    if leave_request.second_approver_id is None:
        raise ConflictError("No Level 2 backup approver is configured for this request.")
    if leave_request.user_id == leave_request.second_approver_id:
        raise ConflictError("Level 2 approver cannot be the same as the requester.")

    user_repository = UserRepository(session)
    backup_approver = await user_repository.get_by_id(leave_request.second_approver_id)
    if backup_approver is None or not backup_approver.is_active:
        raise ConflictError("Level 2 backup approver is not available.")

    if leave_request.first_approver_status != LeaveRequestStatus.PENDING.value:
        raise ConflictError("Level 1 approver has already acted on this request.")

    now = utc_now()
    if leave_request.first_approver_id is not None:
        for assignment in leave_request.approver_pool:
            if (
                assignment.approver_id == leave_request.first_approver_id
                and assignment.status == LeaveRequestStatus.PENDING.value
            ):
                assignment.status = LeaveRequestStatus.CANCELLED.value
                assignment.acted_at = now

    leave_request.first_approver_status = LeaveRequestStatus.CANCELLED.value
    leave_request.first_approver_at = now
    leave_request.second_approver_status = LeaveRequestStatus.PENDING.value
    leave_request.second_approver_at = None
    leave_request.escalated_to_backup_at = now
    leave_request.escalated_to_backup_by_id = current_user.id

    backup_assignment = next(
        (
            assignment
            for assignment in leave_request.approver_pool
            if assignment.approver_id == leave_request.second_approver_id
        ),
        None,
    )
    if backup_assignment is None:
        leave_request.approver_pool.append(
            LeaveRequestApprover(
                approver_id=leave_request.second_approver_id,
                status=LeaveRequestStatus.PENDING.value,
            )
        )
    else:
        backup_assignment.status = LeaveRequestStatus.PENDING.value
        backup_assignment.acted_at = None

    leave_request = await repository.save(leave_request)
    requester_name = _user_display_name(leave_request.user) if leave_request.user else "A user"
    leave_type = _leave_type_label(leave_request.leave_type)
    await _notify_user(
        session,
        recipient_id=leave_request.second_approver_id,
        sender_id=current_user.id,
        content=(
            f"{requester_name}'s {leave_type} leave request for "
            f"{leave_request.leave_date.isoformat()} was escalated to you as backup approver."
        ),
        url=f"/leave/inbox?leave_id={leave_request.id}",
    )
    return leave_request

async def list_leave_credits(
    session: AsyncSession,
    user_id: UUID | None = None,
    department_id: int | None = None,
    leave_type: str | None = None,
) -> list[LeaveCreditSnapshot]:
    leave_type_policy = await _resolve_leave_type_policy(session, leave_type)
    users = await UserRepository(session).list(
        department_id=department_id,
        include_superusers=True,
    )
    if user_id is not None:
        users = [user for user in users if user.id == user_id]

    snapshots: list[LeaveCreditSnapshot] = []
    as_of = local_today()
    for user in users:
        cycle_start = _credit_cycle_start(user, as_of)
        used_credits = (
            await LeaveRequestRepository(session).count_approved_by_user_ids_for_leave_type(
                [user.id],
                leave_type_policy.code,
                approved_since=cycle_start,
                paid_only=True,
            )
            ).get(user.id, Decimal("0.00"))
        used_credits_value = float(used_credits)
        credits = round(_calculate_total_credits(user, leave_type_policy, as_of), 2)
        remaining_credits = round(max(credits - used_credits_value, 0), 2)
        snapshots.append(
            {
                "user_id": user.id,
                "leave_type": leave_type_policy.code,
                "credits": credits,
                "used_credits": used_credits_value,
                "remaining_credits": remaining_credits,
                "user": user,
                "created_at": None,
                "updated_at": None,
            }
        )

    return snapshots


async def get_my_leave_credit(
    session: AsyncSession, user_id: UUID, leave_type: str | None = None
) -> LeaveCreditSnapshot:
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    leave_type_policy = await _resolve_leave_type_policy(session, leave_type)
    as_of = local_today()
    cycle_start = _credit_cycle_start(user, as_of)
    used_credits_by_user_id = (
        await LeaveRequestRepository(session).count_approved_by_user_ids_for_leave_type(
            [user.id],
            leave_type_policy.code,
            approved_since=cycle_start,
            paid_only=True,
        )
    )
    used_credits = float(used_credits_by_user_id.get(user.id, Decimal("0.00")))
    credits = round(_calculate_total_credits(user, leave_type_policy, as_of), 2)
    remaining_credits = round(max(credits - used_credits, 0), 2)

    return {
        "user_id": user.id,
        "leave_type": leave_type_policy.code,
        "credits": credits,
        "used_credits": used_credits,
        "remaining_credits": remaining_credits,
        "user": user,
        "created_at": None,
        "updated_at": None,
    }


async def set_leave_credit(
    session: AsyncSession, user_id: UUID, payload: LeaveCreditUpsertRequest
) -> LeaveCredit:
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    repository = LeaveCreditRepository(session)
    leave_credit = await repository.get_by_user_id(user_id)
    if leave_credit is None:
        leave_credit = LeaveCredit(
            user_id=user_id,
            credits=Decimal(str(payload.credits)),
            used_credits=0,
        )
        leave_credit = await repository.create(leave_credit)
        await _notify_user(
            session,
            recipient_id=user_id,
            sender_id=None,
            content=f"Your annual leave credit was set to {leave_credit.credits} day(s).",
            url="/leave",
        )
        return leave_credit

    leave_credit.credits = Decimal(str(payload.credits))
    leave_credit = await repository.save(leave_credit)
    await _notify_user(
        session,
        recipient_id=user_id,
        sender_id=None,
        content=f"Your annual leave credit was updated to {leave_credit.credits} day(s).",
        url="/leave",
    )
    return leave_credit


async def reset_leave_credit(session: AsyncSession, user_id: UUID) -> LeaveCredit:
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise NotFoundError("User not found.")

    leave_credit = await _ensure_leave_credit(session, user_id)
    leave_credit.used_credits = 0
    leave_credit = await LeaveCreditRepository(session).save(leave_credit)
    await _notify_user(
        session,
        recipient_id=user_id,
        sender_id=None,
        content=(
            "Your leave usage was reset and all configured leave credits are now available."
        ),
        url="/leave",
    )
    return leave_credit
