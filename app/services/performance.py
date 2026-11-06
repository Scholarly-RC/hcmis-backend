from __future__ import annotations

import copy
from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.core.time import utc_now
from app.models.performance import (
    Announcement,
    Evaluation,
    Poll,
    PollChoice,
    PollVote,
    Questionnaire,
    SharedResource,
    UserEvaluation,
)
from app.models.user import User
from app.repositories.performance import (
    AnnouncementRepository,
    EvaluationRepository,
    PollRepository,
    QuestionnaireRepository,
    SharedResourceRepository,
    UserEvaluationRepository,
)
from app.repositories.users import UserRepository
from app.services.notifications import (
    create_notification_if_possible,
    create_notifications_if_possible,
    list_active_user_ids,
)
from app.services.shared_resources_storage import (
    delete_stored_resource_file,
    get_stored_resource_download_url,
    save_uploaded_resource_file,
)
from app.schemas.performance import (
    AnnouncementCreateRequest,
    AnnouncementRead,
    AnnouncementUpdateRequest,
    EvaluationAssignmentRequest,
    EvaluationCreateRequest,
    UserEvaluationAggregateRead,
    UserEvaluationDomainSummaryRead,
    EvaluationSummaryRead,
    EvaluationUpdateRequest,
    FeedItemRead,
    PollCreateRequest,
    PollChoiceRead,
    PollRead,
    PollUpdateRequest,
    PollVoteSubmitRequest,
    QuestionnaireCreateRequest,
    QuestionnaireUpdateRequest,
    SharedResourceAccessReplaceRequest,
    SharedResourceCreateRequest,
    SharedResourceRead,
    SharedResourceUpdateRequest,
    UserEvaluationCreateRequest,
    UserEvaluationUpdateRequest,
)


def _questionnaire_content(questionnaire: Questionnaire) -> list[dict[str, object]]:
    content = questionnaire.content if isinstance(questionnaire.content, dict) else {}
    data = content.get("questionnaire_content", [])
    if not isinstance(data, list):
        return []
    return [domain for domain in data if isinstance(domain, dict)]


def _user_display_name(user: User | None) -> str:
    if user is None:
        return "A user"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return full_name or user.email


def _copy_questionnaire_content(questionnaire: Questionnaire) -> list[dict]:
    return copy.deepcopy(_questionnaire_content(questionnaire))


def _current_domain_key(domain: dict, index: int) -> str:
    domain_number = domain.get("domain_number")
    if domain_number is not None:
        return str(domain_number)
    domain_name = domain.get("domain_name")
    if domain_name:
        return str(domain_name)
    return f"domain_{index + 1}"


def _rating_value(value: object) -> float:
    if value in (None, "", False):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    return 0.0


def _evaluation_requires_peer_feedback(evaluation: Evaluation) -> bool:
    return bool(evaluation.evaluator_id != evaluation.user_evaluation.evaluatee_id)


def _evaluation_answer_counts(evaluation: Evaluation) -> tuple[int, int]:
    content_data = evaluation.content_data or []
    question_count = 0
    answered_question_count = 0

    for domain in content_data:
        questions = domain.get("questions") if isinstance(domain, dict) else []
        if not isinstance(questions, list):
            continue
        question_count += len(questions)
        for question in questions:
            rating = question.get("rating") if isinstance(question, dict) else None
            if rating not in (None, "", False):
                answered_question_count += 1

    if _evaluation_requires_peer_feedback(evaluation):
        question_count += 2
        if evaluation.positive_feedback and evaluation.positive_feedback.strip():
            answered_question_count += 1
        if evaluation.improvement_suggestion and evaluation.improvement_suggestion.strip():
            answered_question_count += 1

    return answered_question_count, question_count


def _ensure_evaluation_complete(evaluation: Evaluation) -> None:
    answered, total = _evaluation_answer_counts(evaluation)
    if answered != total:
        raise ConflictError("Evaluation is incomplete. Answer all required fields before submitting.")


def _assert_can_manage_evaluation(item: Evaluation, current_user_id: UUID, is_staff: bool) -> None:
    if is_staff:
        return
    if item.evaluator_id != current_user_id:
        raise PermissionDeniedError("Only assigned evaluator can modify this evaluation.")


def _assert_can_rate_evaluation(item: Evaluation, current_user_id: UUID) -> None:
    if item.evaluator_id != current_user_id:
        raise PermissionDeniedError("Only assigned evaluator can rate this evaluation.")


def _assert_cycle_allows_editing(item: Evaluation, is_staff: bool) -> None:
    if is_staff:
        return
    if item.user_evaluation.is_finalized is not True:
        raise ConflictError("Evaluation cycle is not open yet.")
    if item.date_submitted is not None:
        raise ConflictError("Submitted evaluations can no longer be edited.")


def _find_rating(
    evaluations: list[Evaluation],
    domain_key: str,
    indicator_number: str,
) -> float | None:
    for evaluation in evaluations:
        for index, domain in enumerate(evaluation.content_data or []):
            if not isinstance(domain, dict):
                continue
            if _current_domain_key(domain, index) != domain_key:
                continue
            questions = domain.get("questions")
            if not isinstance(questions, list):
                continue
            for question in questions:
                if not isinstance(question, dict):
                    continue
                if str(question.get("indicator_number", "")) == indicator_number:
                    rating = question.get("rating")
                    if rating in (None, "", False):
                        continue
                    return _rating_value(rating)
    return None


def _evaluation_summary(
    evaluation: Evaluation,
) -> tuple[int, int, dict[str, float], float | None]:
    content_data = evaluation.content_data or []
    question_count = 0
    answered_question_count = 0
    domain_means: dict[str, float] = {}
    means: list[float] = []

    for index, domain in enumerate(content_data):
        questions = domain.get("questions") or []
        if not isinstance(questions, list):
            continue
        domain_question_count = len(questions)
        question_count += domain_question_count
        rating_total = 0.0
        for question in questions:
            rating = question.get("rating") if isinstance(question, dict) else None
            if rating not in (None, "", False):
                answered_question_count += 1
                rating_total += _rating_value(rating)
        if domain_question_count:
            mean = round(rating_total / domain_question_count, 2)
            domain_means[_current_domain_key(domain, index)] = mean
            means.append(mean)

    overall_mean = round(sum(means) / len(means), 2) if means else None
    return answered_question_count, question_count, domain_means, overall_mean


ANNOUNCEMENT_STATUSES = {"draft", "published", "archived"}
POLL_STATUSES = {"draft", "published", "closed", "archived"}
EMPLOYEE_QUESTIONNAIRE_CODE = "NIMER-EES"
ADMINISTRATOR_QUESTIONNAIRE_CODE = "NIMER-NAPES"


def _is_employee_user_role(role: str | None) -> bool:
    normalized = (role or "EMP").strip().upper()
    return normalized in {"", "EMP"}


def _assert_questionnaire_matches_evaluatee_role(*, evaluatee_role: str | None, questionnaire_code: str) -> None:
    code = questionnaire_code.strip().upper()
    if code not in {EMPLOYEE_QUESTIONNAIRE_CODE, ADMINISTRATOR_QUESTIONNAIRE_CODE}:
        return

    is_employee = _is_employee_user_role(evaluatee_role)
    if is_employee and code != EMPLOYEE_QUESTIONNAIRE_CODE:
        raise ConflictError(
            "Employees must use the employee questionnaire "
            f"({EMPLOYEE_QUESTIONNAIRE_CODE})."
        )
    if not is_employee and code != ADMINISTRATOR_QUESTIONNAIRE_CODE:
        raise ConflictError(
            "Non-employees must use the administrator questionnaire "
            f"({ADMINISTRATOR_QUESTIONNAIRE_CODE})."
        )


def _normalize_statuses(
    statuses: list[str] | None,
    allowed: set[str],
    fallback: list[str],
) -> list[str]:
    if not statuses:
        return fallback
    cleaned = [status.strip().lower() for status in statuses if status.strip()]
    invalid = [status for status in cleaned if status not in allowed]
    if invalid:
        raise ConflictError(f"Invalid status filter: {invalid[0]}")
    return cleaned


def _to_poll_read(poll: Poll, current_user_id: UUID | None = None) -> PollRead:
    choice_reads: list[PollChoiceRead] = []
    for choice in sorted(poll.choices, key=lambda item: item.position):
        vote_count = sum(1 for vote in poll.votes if vote.choice_id == choice.id)
        choice_reads.append(
            PollChoiceRead(
                id=choice.id,
                poll_id=choice.poll_id,
                text=choice.text,
                position=choice.position,
                vote_count=vote_count,
            )
        )

    user_vote_choice_ids: list[int] = []
    if current_user_id is not None:
        user_vote_choice_ids = [
            vote.choice_id for vote in poll.votes if vote.user_id == current_user_id
        ]
        user_vote_choice_ids.sort()

    return PollRead(
        id=poll.id,
        author_id=poll.author_id,
        question=poll.question,
        description=poll.description,
        allow_multiple_choices=poll.allow_multiple_choices,
        status=poll.status,
        published_at=poll.published_at,
        closed_at=poll.closed_at,
        archived_at=poll.archived_at,
        created_at=poll.created_at,
        updated_at=poll.updated_at,
        choices=choice_reads,
        user_vote_choice_ids=user_vote_choice_ids,
    )


def _validate_poll_choices(choices: list[int], allow_multiple: bool) -> list[int]:
    unique_choices = sorted(set(choices))
    if not unique_choices:
        raise ConflictError("At least one poll choice is required.")
    if not allow_multiple and len(unique_choices) != 1:
        raise ConflictError("This poll allows only one choice.")
    return unique_choices


def _resource_shared_user_ids(resource: SharedResource) -> list[UUID]:
    return [item.user_id for item in resource.shares]


def _resource_confidential_user_ids(resource: SharedResource) -> list[UUID]:
    return [item.user_id for item in resource.confidential_access]


def _resource_can_be_seen_by(resource: SharedResource, user_id: UUID) -> bool:
    if resource.uploader_id == user_id:
        return True
    shared_user_ids = _resource_shared_user_ids(resource)
    if user_id not in shared_user_ids:
        return False
    if not resource.is_confidential:
        return True
    return user_id in _resource_confidential_user_ids(resource)


def _resource_can_be_managed_by(resource: SharedResource, current_user_id: UUID, is_staff: bool) -> bool:
    return is_staff or resource.uploader_id == current_user_id


def _normalized_uuid_list(values: list[UUID]) -> list[UUID]:
    unique_by_value: dict[str, UUID] = {}
    for value in values:
        unique_by_value[str(value)] = value
    return [unique_by_value[key] for key in sorted(unique_by_value)]


def _to_shared_resource_read(resource: SharedResource) -> SharedResourceRead:
    return SharedResourceRead(
        id=resource.id,
        uploader_id=resource.uploader_id,
        uploader=resource.uploader,
        resource_name=resource.resource_name,
        description=resource.description,
        original_filename=resource.original_filename,
        content_type=resource.content_type,
        size_bytes=resource.size_bytes,
        is_confidential=resource.is_confidential,
        shared_user_ids=_resource_shared_user_ids(resource),
        confidential_access_user_ids=_resource_confidential_user_ids(resource),
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


async def list_questionnaires(
    session: AsyncSession, include_inactive: bool = False
) -> list[Questionnaire]:
    return await QuestionnaireRepository(session).list(include_inactive=include_inactive)


async def create_questionnaire(
    session: AsyncSession, payload: QuestionnaireCreateRequest
) -> Questionnaire:
    repository = QuestionnaireRepository(session)
    code = payload.code.strip().upper()
    if await repository.get_by_code(code):
        raise ConflictError("Questionnaire code already exists.")
    questionnaire = Questionnaire(
        code=code,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        content=payload.content,
        is_active=payload.is_active,
    )
    return await repository.create(questionnaire)


async def update_questionnaire(
    session: AsyncSession, questionnaire_id: int, payload: QuestionnaireUpdateRequest
) -> Questionnaire:
    repository = QuestionnaireRepository(session)
    questionnaire = await repository.get_by_id(questionnaire_id)
    if questionnaire is None:
        raise NotFoundError("Questionnaire not found.")
    if payload.code is not None:
        code = payload.code.strip().upper()
        existing = await repository.get_by_code(code)
        if existing is not None and existing.id != questionnaire_id:
            raise ConflictError("Questionnaire code already exists.")
        questionnaire.code = code
    if payload.title is not None:
        questionnaire.title = payload.title.strip()
    if payload.description is not None:
        questionnaire.description = payload.description.strip() if payload.description else None
    if payload.content is not None:
        questionnaire.content = payload.content
    if payload.is_active is not None:
        questionnaire.is_active = payload.is_active
    return await repository.save(questionnaire)


async def delete_questionnaire(session: AsyncSession, questionnaire_id: int) -> None:
    repository = QuestionnaireRepository(session)
    questionnaire = await repository.get_by_id(questionnaire_id)
    if questionnaire is None:
        raise NotFoundError("Questionnaire not found.")
    await repository.delete(questionnaire)


async def list_user_evaluations(
    session: AsyncSession,
    evaluatee_id: UUID | None = None,
    questionnaire_id: int | None = None,
    quarter: str | None = None,
    year: int | None = None,
    is_finalized: bool | None = None,
    current_user_id: UUID | None = None,
    is_staff: bool = False,
    evaluator_id: UUID | None = None,
    is_submitted: bool | None = None,
) -> list[UserEvaluation]:
    if (
        evaluator_id is not None
        and current_user_id is not None
        and evaluator_id != current_user_id
        and not is_staff
    ):
        raise PermissionDeniedError("Cannot list evaluations assigned to another evaluator.")

    items = await UserEvaluationRepository(session).list(
        evaluatee_id=evaluatee_id,
        questionnaire_id=questionnaire_id,
        quarter=quarter,
        year=year,
        is_finalized=is_finalized,
        evaluator_id=evaluator_id,
        is_submitted=is_submitted,
    )
    if is_staff or current_user_id is None:
        return items

    visible_items: list[UserEvaluation] = []
    for item in items:
        if item.evaluatee_id == current_user_id:
            visible_items.append(item)
            continue
        if any(evaluation.evaluator_id == current_user_id for evaluation in item.evaluations):
            visible_items.append(item)
    return visible_items


async def create_user_evaluation(
    session: AsyncSession, payload: UserEvaluationCreateRequest
) -> UserEvaluation:
    user_repository = UserRepository(session)
    questionnaire_repository = QuestionnaireRepository(session)
    user = await user_repository.get_by_id(payload.evaluatee_id)
    if user is None:
        raise NotFoundError("User not found.")
    questionnaire = await questionnaire_repository.get_by_id(payload.questionnaire_id)
    if questionnaire is None:
        raise NotFoundError("Questionnaire not found.")
    _assert_questionnaire_matches_evaluatee_role(
        evaluatee_role=user.role,
        questionnaire_code=questionnaire.code,
    )

    repository = UserEvaluationRepository(session)
    existing = await repository.get_by_identity(
        payload.evaluatee_id,
        payload.questionnaire_id,
        payload.quarter,
        payload.year,
    )
    if existing is not None:
        raise ConflictError("User evaluation already exists.")

    item = UserEvaluation(
        evaluatee_id=payload.evaluatee_id,
        questionnaire_id=payload.questionnaire_id,
        quarter=payload.quarter,
        year=payload.year,
        is_finalized=False,
    )
    created = await repository.create(item)

    # Always seed self-evaluation so each cycle starts with a stable baseline assignment.
    await EvaluationRepository(session).create(
        Evaluation(
            evaluator_id=created.evaluatee_id,
            user_evaluation_id=created.id,
            questionnaire_id=created.questionnaire_id,
            content_data=_copy_questionnaire_content(questionnaire),
        )
    )
    refreshed = await repository.get_by_id(created.id)
    if refreshed is None:
        raise NotFoundError("User evaluation not found.")
    return refreshed


async def update_user_evaluation(
    session: AsyncSession, user_evaluation_id: int, payload: UserEvaluationUpdateRequest
) -> UserEvaluation:
    repository = UserEvaluationRepository(session)
    item = await repository.get_by_id(user_evaluation_id)
    if item is None:
        raise NotFoundError("User evaluation not found.")
    if payload.questionnaire_id is not None:
        questionnaire = await QuestionnaireRepository(session).get_by_id(payload.questionnaire_id)
        if questionnaire is None:
            raise NotFoundError("Questionnaire not found.")
        _assert_questionnaire_matches_evaluatee_role(
            evaluatee_role=item.evaluatee.role if item.evaluatee else None,
            questionnaire_code=questionnaire.code,
        )
        item.questionnaire_id = payload.questionnaire_id
    if payload.quarter is not None:
        item.quarter = payload.quarter
    if payload.year is not None:
        item.year = payload.year
    if payload.is_finalized is not None:
        item.is_finalized = payload.is_finalized
    return await repository.save(item)


async def toggle_user_evaluation_finalized(
    session: AsyncSession, user_evaluation_id: int
) -> UserEvaluation:
    repository = UserEvaluationRepository(session)
    item = await repository.get_by_id(user_evaluation_id)
    if item is None:
        raise NotFoundError("User evaluation not found.")
    next_state = not item.is_finalized
    if next_state:
        has_self = any(evaluation.evaluator_id == item.evaluatee_id for evaluation in item.evaluations)
        peer_count = sum(1 for evaluation in item.evaluations if evaluation.evaluator_id != item.evaluatee_id)
        if not has_self:
            raise ConflictError("Self-evaluation assignment is missing.")
        if peer_count < 1:
            raise ConflictError("At least one peer evaluator is required before finalizing.")
    item.is_finalized = next_state
    saved = await repository.save(item)
    if next_state:
        recipient_ids = _normalized_uuid_list(
            [
                evaluation.evaluator_id
                for evaluation in saved.evaluations
                if evaluation.evaluator_id != saved.evaluatee_id
            ]
        )
        if recipient_ids:
            evaluatee_name = _user_display_name(saved.evaluatee)
            await create_notifications_if_possible(
                session,
                recipient_ids=recipient_ids,
                content=(
                    f"You were assigned to evaluate {evaluatee_name} "
                    f"for Q{saved.quarter} {saved.year}."
                ),
                url=f"/performance-evaluations?cycle_id={saved.id}",
            )
    return saved


async def assign_user_evaluation_evaluator(
    session: AsyncSession,
    user_evaluation_id: int,
    payload: EvaluationAssignmentRequest,
) -> Evaluation:
    user_evaluation_repository = UserEvaluationRepository(session)
    user_evaluation = await user_evaluation_repository.get_by_id(user_evaluation_id)
    if user_evaluation is None:
        raise NotFoundError("User evaluation not found.")
    if user_evaluation.is_finalized:
        raise ConflictError("Cannot modify evaluator assignments for finalized cycles.")

    evaluator = await UserRepository(session).get_by_id(payload.evaluator_id)
    if evaluator is None:
        raise NotFoundError("User not found.")

    evaluation_repository = EvaluationRepository(session)
    existing = await evaluation_repository.get_by_identity(
        user_evaluation_id=user_evaluation.id,
        evaluator_id=payload.evaluator_id,
    )
    if existing is not None:
        return existing

    created = await evaluation_repository.create(
        Evaluation(
            evaluator_id=payload.evaluator_id,
            user_evaluation_id=user_evaluation.id,
            questionnaire_id=user_evaluation.questionnaire_id,
            content_data=_copy_questionnaire_content(user_evaluation.questionnaire),
        )
    )
    return created


async def unassign_user_evaluation_evaluator(
    session: AsyncSession,
    user_evaluation_id: int,
    evaluator_id: UUID,
) -> None:
    user_evaluation_repository = UserEvaluationRepository(session)
    user_evaluation = await user_evaluation_repository.get_by_id(user_evaluation_id)
    if user_evaluation is None:
        raise NotFoundError("User evaluation not found.")
    if user_evaluation.is_finalized:
        raise ConflictError("Cannot modify evaluator assignments for finalized cycles.")
    if evaluator_id == user_evaluation.evaluatee_id:
        raise ConflictError("Self-evaluation assignment cannot be removed.")

    evaluation_repository = EvaluationRepository(session)
    existing = await evaluation_repository.get_by_identity(
        user_evaluation_id=user_evaluation.id,
        evaluator_id=evaluator_id,
    )
    if existing is None:
        raise NotFoundError("Evaluation assignment not found.")
    await evaluation_repository.delete(existing)


async def reset_user_evaluation(
    session: AsyncSession, user_evaluation_id: int
) -> UserEvaluation:
    repository = UserEvaluationRepository(session)
    item = await repository.get_by_id(user_evaluation_id)
    if item is None:
        raise NotFoundError("User evaluation not found.")
    item.is_finalized = False
    for evaluation in item.evaluations:
        questionnaire = evaluation.questionnaire
        evaluation.content_data = _copy_questionnaire_content(questionnaire)
        evaluation.positive_feedback = None
        evaluation.improvement_suggestion = None
        evaluation.date_submitted = None
    return await repository.save(item)


async def delete_user_evaluation(session: AsyncSession, user_evaluation_id: int) -> None:
    repository = UserEvaluationRepository(session)
    item = await repository.get_by_id(user_evaluation_id)
    if item is None:
        raise NotFoundError("User evaluation not found.")
    await repository.delete(item)


async def list_evaluations(
    session: AsyncSession,
    user_evaluation_id: int | None = None,
    evaluator_id: UUID | None = None,
    is_submitted: bool | None = None,
    current_user_id: UUID | None = None,
    is_staff: bool = False,
) -> list[Evaluation]:
    evaluations = await EvaluationRepository(session).list(
        user_evaluation_id=user_evaluation_id,
        evaluator_id=evaluator_id,
        is_submitted=is_submitted,
    )
    if is_staff or current_user_id is None:
        return evaluations
    return [
        evaluation
        for evaluation in evaluations
        if (
            evaluation.evaluator_id == current_user_id
            or evaluation.user_evaluation.evaluatee_id == current_user_id
        )
    ]


async def create_evaluation(
    session: AsyncSession,
    user_evaluation_id: int,
    current_user_id: UUID,
    payload: EvaluationCreateRequest,
    is_staff: bool = False,
) -> Evaluation:
    user_repository = UserRepository(session)
    evaluator_id = payload.evaluator_id if payload.evaluator_id is not None else current_user_id
    if not is_staff and evaluator_id != current_user_id:
        raise PermissionDeniedError("Cannot create evaluation for another user.")

    evaluator = await user_repository.get_by_id(evaluator_id)
    if evaluator is None:
        raise NotFoundError("User not found.")

    user_evaluation_repository = UserEvaluationRepository(session)
    user_evaluation = await user_evaluation_repository.get_by_id(user_evaluation_id)
    if user_evaluation is None:
        raise NotFoundError("User evaluation not found.")

    repository = EvaluationRepository(session)
    existing = await repository.get_by_identity(user_evaluation_id, evaluator_id)
    if existing is not None:
        return await update_evaluation(
            session,
            existing.id,
            EvaluationUpdateRequest(
                positive_feedback=payload.positive_feedback,
                improvement_suggestion=payload.improvement_suggestion,
                content_data=payload.content_data,
            ),
            current_user_id=current_user_id,
        )

    if not is_staff:
        raise PermissionDeniedError("Evaluator is not assigned to this cycle.")
    if evaluator_id == current_user_id:
        raise PermissionDeniedError("Evaluator is not assigned to this cycle.")
    if (
        payload.content_data is not None
        or payload.positive_feedback is not None
        or payload.improvement_suggestion is not None
    ):
        raise PermissionDeniedError("Staff cannot rate for another evaluator.")

    questionnaire = user_evaluation.questionnaire
    item = Evaluation(
        evaluator_id=evaluator_id,
        user_evaluation_id=user_evaluation_id,
        questionnaire_id=user_evaluation.questionnaire_id,
        content_data=payload.content_data or _copy_questionnaire_content(questionnaire),
        positive_feedback=payload.positive_feedback.strip() if payload.positive_feedback else None,
        improvement_suggestion=(
            payload.improvement_suggestion.strip() if payload.improvement_suggestion else None
        ),
    )
    return await repository.create(item)


async def update_evaluation(
    session: AsyncSession,
    evaluation_id: int,
    payload: EvaluationUpdateRequest,
    current_user_id: UUID,
) -> Evaluation:
    repository = EvaluationRepository(session)
    item = await repository.get_by_id(evaluation_id)
    if item is None:
        raise NotFoundError("Evaluation not found.")
    _assert_can_rate_evaluation(item, current_user_id=current_user_id)
    _assert_cycle_allows_editing(item, is_staff=False)
    if payload.content_data is not None:
        item.content_data = payload.content_data
    if payload.positive_feedback is not None:
        item.positive_feedback = payload.positive_feedback.strip() or None
    if payload.improvement_suggestion is not None:
        item.improvement_suggestion = payload.improvement_suggestion.strip() or None
    return await repository.save(item)


async def submit_evaluation(
    session: AsyncSession,
    evaluation_id: int,
    current_user_id: UUID,
) -> Evaluation:
    repository = EvaluationRepository(session)
    item = await repository.get_by_id(evaluation_id)
    if item is None:
        raise NotFoundError("Evaluation not found.")
    _assert_can_rate_evaluation(item, current_user_id=current_user_id)
    _assert_cycle_allows_editing(item, is_staff=False)
    _ensure_evaluation_complete(item)
    item.date_submitted = utc_now()
    item = await repository.save(item)
    evaluator_name = _user_display_name(item.evaluator)
    await create_notification_if_possible(
        session,
        recipient_id=item.user_evaluation.evaluatee_id,
        sender_id=item.evaluator_id,
        content=f"{evaluator_name} submitted a performance evaluation for you.",
        url=f"/performance-evaluations?cycle_id={item.user_evaluation_id}",
    )
    return item


async def reset_evaluation(
    session: AsyncSession,
    evaluation_id: int,
    current_user_id: UUID,
    is_staff: bool = False,
) -> Evaluation:
    repository = EvaluationRepository(session)
    item = await repository.get_by_id(evaluation_id)
    if item is None:
        raise NotFoundError("Evaluation not found.")
    _assert_can_manage_evaluation(item, current_user_id=current_user_id, is_staff=is_staff)
    questionnaire = item.questionnaire
    item.content_data = _copy_questionnaire_content(questionnaire)
    item.positive_feedback = None
    item.improvement_suggestion = None
    item.date_submitted = None
    return await repository.save(item)


async def delete_evaluation(
    session: AsyncSession,
    evaluation_id: int,
    current_user_id: UUID,
    is_staff: bool = False,
) -> None:
    repository = EvaluationRepository(session)
    item = await repository.get_by_id(evaluation_id)
    if item is None:
        raise NotFoundError("Evaluation not found.")
    _assert_can_manage_evaluation(item, current_user_id=current_user_id, is_staff=is_staff)
    await repository.delete(item)


async def get_evaluation_summary(
    session: AsyncSession,
    evaluation_id: int,
    current_user_id: UUID,
    is_staff: bool = False,
) -> EvaluationSummaryRead:
    repository = EvaluationRepository(session)
    item = await repository.get_by_id(evaluation_id)
    if item is None:
        raise NotFoundError("Evaluation not found.")
    if not is_staff and (
        item.evaluator_id != current_user_id
        and item.user_evaluation.evaluatee_id != current_user_id
    ):
        raise PermissionDeniedError("Not enough permissions to view this evaluation summary.")
    answered_question_count, question_count, domain_means, overall_mean = _evaluation_summary(item)
    return EvaluationSummaryRead(
        evaluation_id=item.id,
        is_submitted=item.date_submitted is not None,
        answered_question_count=answered_question_count,
        question_count=question_count,
        domain_means=domain_means,
        overall_mean=overall_mean,
        positive_feedback=item.positive_feedback,
        improvement_suggestion=item.improvement_suggestion,
        self_evaluation=bool(item.evaluator_id == item.user_evaluation.evaluatee_id),
    )


async def get_user_evaluation_aggregate_summary(
    session: AsyncSession,
    user_evaluation_id: int,
    current_user_id: UUID,
    is_staff: bool = False,
) -> UserEvaluationAggregateRead:
    user_evaluation = await UserEvaluationRepository(session).get_by_id(user_evaluation_id)
    if user_evaluation is None:
        raise NotFoundError("User evaluation not found.")

    if not is_staff:
        if user_evaluation.is_finalized is not True:
            raise PermissionDeniedError("Cycle summary is available only for finalized cycles.")
        allowed_evaluator_ids = {evaluation.evaluator_id for evaluation in user_evaluation.evaluations}
        if (
            current_user_id != user_evaluation.evaluatee_id
            and current_user_id not in allowed_evaluator_ids
        ):
            raise PermissionDeniedError("Not enough permissions to view this cycle summary.")

        if current_user_id == user_evaluation.evaluatee_id:
            self_evaluation = next(
                (
                    evaluation
                    for evaluation in user_evaluation.evaluations
                    if evaluation.evaluator_id == user_evaluation.evaluatee_id
                ),
                None,
            )
            if self_evaluation is None or self_evaluation.date_submitted is None:
                raise PermissionDeniedError(
                    "Summary becomes visible after submitting your self-evaluation."
                )

    submitted_evaluations = [
        evaluation for evaluation in user_evaluation.evaluations if evaluation.date_submitted is not None
    ]
    self_evaluations = [
        evaluation for evaluation in submitted_evaluations if evaluation.evaluator_id == user_evaluation.evaluatee_id
    ]
    peer_evaluations = [
        evaluation for evaluation in submitted_evaluations if evaluation.evaluator_id != user_evaluation.evaluatee_id
    ]

    content = _questionnaire_content(user_evaluation.questionnaire)
    domains: list[UserEvaluationDomainSummaryRead] = []
    for index, domain in enumerate(content):
        questions = domain.get("questions") if isinstance(domain, dict) else []
        if not isinstance(questions, list):
            continue

        self_ratings: list[float] = []
        peer_ratings: list[float] = []
        for question in questions:
            if not isinstance(question, dict):
                continue
            question_data = cast(dict[str, object], question)
            raw_indicator_number = question_data.get("indicator_number")
            indicator_number = str(raw_indicator_number) if raw_indicator_number is not None else ""
            if not indicator_number:
                continue
            self_ratings.append(
                _rating_value(
                    _find_rating(
                        evaluations=self_evaluations,
                        domain_key=_current_domain_key(domain, index),
                        indicator_number=indicator_number,
                    )
                )
            )
            peer_ratings.append(
                _rating_value(
                    _find_rating(
                        evaluations=peer_evaluations,
                        domain_key=_current_domain_key(domain, index),
                        indicator_number=indicator_number,
                    )
                )
            )

        domain_self_mean = round(sum(self_ratings) / len(self_ratings), 2) if self_ratings else 0.0
        domain_peer_mean = round(sum(peer_ratings) / len(peer_ratings), 2) if peer_ratings else 0.0
        domains.append(
            UserEvaluationDomainSummaryRead(
                domain_key=_current_domain_key(domain, index),
                self_rating_mean=domain_self_mean,
                peer_rating_mean=domain_peer_mean,
            )
        )

    self_overall = round(sum(item.self_rating_mean for item in domains) / len(domains), 2) if domains else 0.0
    peer_overall = round(sum(item.peer_rating_mean for item in domains) / len(domains), 2) if domains else 0.0

    peer_positive_feedback = sorted(
        {
            evaluation.positive_feedback.strip()
            for evaluation in peer_evaluations
            if evaluation.positive_feedback and evaluation.positive_feedback.strip()
        }
    )
    peer_improvement = sorted(
        {
            evaluation.improvement_suggestion.strip()
            for evaluation in peer_evaluations
            if evaluation.improvement_suggestion and evaluation.improvement_suggestion.strip()
        }
    )

    return UserEvaluationAggregateRead(
        user_evaluation_id=user_evaluation.id,
        evaluatee_id=user_evaluation.evaluatee_id,
        questionnaire_id=user_evaluation.questionnaire_id,
        quarter=user_evaluation.quarter,
        year=user_evaluation.year,
        is_finalized=user_evaluation.is_finalized,
        self_rating_overall_mean=self_overall,
        peer_rating_overall_mean=peer_overall,
        domains=domains,
        peer_positive_feedback=peer_positive_feedback,
        peer_improvement_suggestions=peer_improvement,
    )


async def list_announcements(
    session: AsyncSession,
    statuses: list[str] | None = None,
) -> list[Announcement]:
    repository = AnnouncementRepository(session)
    normalized_statuses = _normalize_statuses(
        statuses,
        ANNOUNCEMENT_STATUSES,
        fallback=["published"],
    )
    return await repository.list(statuses=normalized_statuses)


async def create_announcement(
    session: AsyncSession,
    current_user_id: UUID,
    payload: AnnouncementCreateRequest,
) -> Announcement:
    repository = AnnouncementRepository(session)
    item = Announcement(
        author_id=current_user_id,
        title=payload.title.strip(),
        summary=payload.summary.strip() if payload.summary else None,
        content=payload.content.strip(),
        status="draft",
    )
    return await repository.create(item)


async def update_announcement(
    session: AsyncSession,
    announcement_id: int,
    payload: AnnouncementUpdateRequest,
) -> Announcement:
    repository = AnnouncementRepository(session)
    item = await repository.get_by_id(announcement_id)
    if item is None:
        raise NotFoundError("Announcement not found.")
    if item.status == "archived":
        raise ConflictError("Archived announcements can no longer be modified.")
    if payload.title is not None:
        item.title = payload.title.strip()
    if payload.summary is not None:
        item.summary = payload.summary.strip() if payload.summary else None
    if payload.content is not None:
        item.content = payload.content.strip()
    return await repository.save(item)


async def publish_announcement(
    session: AsyncSession,
    announcement_id: int,
) -> Announcement:
    repository = AnnouncementRepository(session)
    item = await repository.get_by_id(announcement_id)
    if item is None:
        raise NotFoundError("Announcement not found.")
    if item.status == "archived":
        raise ConflictError("Archived announcements cannot be published.")
    item.status = "published"
    if item.published_at is None:
        item.published_at = utc_now()
    item = await repository.save(item)
    recipient_ids = await list_active_user_ids(session)
    await create_notifications_if_possible(
        session,
        recipient_ids=recipient_ids,
        sender_id=item.author_id,
        content=f"New announcement published: {item.title}",
        url=f"/announcements-and-polls?announcement_id={item.id}",
    )
    return item


async def archive_announcement(
    session: AsyncSession,
    announcement_id: int,
) -> Announcement:
    repository = AnnouncementRepository(session)
    item = await repository.get_by_id(announcement_id)
    if item is None:
        raise NotFoundError("Announcement not found.")
    item.status = "archived"
    item.archived_at = utc_now()
    return await repository.save(item)


async def unarchive_announcement(
    session: AsyncSession,
    announcement_id: int,
) -> Announcement:
    repository = AnnouncementRepository(session)
    item = await repository.get_by_id(announcement_id)
    if item is None:
        raise NotFoundError("Announcement not found.")
    if item.status != "archived":
        raise ConflictError("Only archived announcements can be unarchived.")
    item.status = "published" if item.published_at is not None else "draft"
    item.archived_at = None
    return await repository.save(item)


async def revert_announcement_to_draft(
    session: AsyncSession,
    announcement_id: int,
) -> Announcement:
    repository = AnnouncementRepository(session)
    item = await repository.get_by_id(announcement_id)
    if item is None:
        raise NotFoundError("Announcement not found.")
    if item.status == "archived":
        raise ConflictError("Archived announcements cannot be moved to draft.")
    if item.status != "published":
        raise ConflictError("Only published announcements can be moved to draft.")
    item.status = "draft"
    item.published_at = None
    return await repository.save(item)


async def list_polls(
    session: AsyncSession,
    current_user_id: UUID,
    statuses: list[str] | None = None,
) -> list[PollRead]:
    repository = PollRepository(session)
    normalized_statuses = _normalize_statuses(
        statuses,
        POLL_STATUSES,
        fallback=["published", "closed"],
    )
    polls = await repository.list(statuses=normalized_statuses)
    return [_to_poll_read(poll, current_user_id=current_user_id) for poll in polls]


async def create_poll(
    session: AsyncSession,
    current_user_id: UUID,
    payload: PollCreateRequest,
) -> PollRead:
    repository = PollRepository(session)
    poll = Poll(
        author_id=current_user_id,
        question=payload.question.strip(),
        description=payload.description.strip() if payload.description else None,
        allow_multiple_choices=payload.allow_multiple_choices,
        status="draft",
    )
    created_poll = await repository.create(poll)

    position = 1
    for choice in payload.choices:
        await repository.add_choice(
            PollChoice(
                poll_id=created_poll.id,
                text=choice.text.strip(),
                position=position,
            )
        )
        position += 1

    refreshed = await repository.get_by_id(created_poll.id)
    if refreshed is None:
        raise NotFoundError("Poll not found.")
    return _to_poll_read(refreshed, current_user_id=current_user_id)


async def update_poll(
    session: AsyncSession,
    poll_id: int,
    payload: PollUpdateRequest,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if poll.status in {"closed", "archived"}:
        raise ConflictError("Closed or archived polls can no longer be modified.")
    if payload.question is not None:
        poll.question = payload.question.strip()
    if payload.description is not None:
        poll.description = payload.description.strip() if payload.description else None
    if payload.allow_multiple_choices is not None:
        poll.allow_multiple_choices = payload.allow_multiple_choices
    saved = await repository.save(poll)
    return _to_poll_read(saved)


async def publish_poll(
    session: AsyncSession,
    poll_id: int,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if len(poll.choices) < 2:
        raise ConflictError("Poll needs at least two choices before publishing.")
    if poll.status == "archived":
        raise ConflictError("Archived polls cannot be published.")
    poll.status = "published"
    if poll.published_at is None:
        poll.published_at = utc_now()
    saved = await repository.save(poll)
    recipient_ids = await list_active_user_ids(session)
    await create_notifications_if_possible(
        session,
        recipient_ids=recipient_ids,
        sender_id=saved.author_id,
        content=f"New poll published: {saved.question}",
        url=f"/announcements-and-polls?poll_id={saved.id}",
    )
    return _to_poll_read(saved)


async def close_poll(
    session: AsyncSession,
    poll_id: int,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if poll.status == "archived":
        raise ConflictError("Archived polls cannot be closed.")
    poll.status = "closed"
    if poll.closed_at is None:
        poll.closed_at = utc_now()
    saved = await repository.save(poll)
    return _to_poll_read(saved)


async def reopen_poll(
    session: AsyncSession,
    poll_id: int,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if poll.status == "archived":
        raise ConflictError("Archived polls cannot be reopened.")
    if poll.status != "closed":
        raise ConflictError("Only closed polls can be reopened.")
    poll.status = "published"
    poll.closed_at = None
    if poll.published_at is None:
        poll.published_at = utc_now()
    saved = await repository.save(poll)
    return _to_poll_read(saved)


async def archive_poll(
    session: AsyncSession,
    poll_id: int,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    poll.status = "archived"
    poll.archived_at = utc_now()
    saved = await repository.save(poll)
    return _to_poll_read(saved)


async def unarchive_poll(
    session: AsyncSession,
    poll_id: int,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if poll.status != "archived":
        raise ConflictError("Only archived polls can be unarchived.")
    if poll.closed_at is not None:
        poll.status = "closed"
    elif poll.published_at is not None:
        poll.status = "published"
    else:
        poll.status = "draft"
    poll.archived_at = None
    saved = await repository.save(poll)
    return _to_poll_read(saved)


async def add_poll_choice(
    session: AsyncSession,
    poll_id: int,
    text: str,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if poll.status != "draft":
        raise ConflictError("Choices can only be modified while poll is in draft.")
    choice_text = text.strip()
    if not choice_text:
        raise ConflictError("Choice text is required.")
    already_exists = any(choice.text.lower() == choice_text.lower() for choice in poll.choices)
    if already_exists:
        raise ConflictError("Poll choice already exists.")
    next_position = max((choice.position for choice in poll.choices), default=0) + 1
    await repository.add_choice(
        PollChoice(
            poll_id=poll.id,
            text=choice_text,
            position=next_position,
        )
    )
    refreshed = await repository.get_by_id(poll.id)
    if refreshed is None:
        raise NotFoundError("Poll not found.")
    return _to_poll_read(refreshed)


async def remove_poll_choice(
    session: AsyncSession,
    poll_id: int,
    choice_id: int,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if poll.status != "draft":
        raise ConflictError("Choices can only be modified while poll is in draft.")
    selected_choice = next((choice for choice in poll.choices if choice.id == choice_id), None)
    if selected_choice is None:
        raise NotFoundError("Poll choice not found.")
    await repository.delete_choice(selected_choice)
    refreshed = await repository.get_by_id(poll.id)
    if refreshed is None:
        raise NotFoundError("Poll not found.")
    if len(refreshed.choices) < 2:
        refreshed.status = "draft"
        refreshed = await repository.save(refreshed)
    return _to_poll_read(refreshed)


async def submit_poll_vote(
    session: AsyncSession,
    poll_id: int,
    current_user_id: UUID,
    payload: PollVoteSubmitRequest,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    if poll.status != "published":
        raise ConflictError("Poll is not open for voting.")

    selected_choice_ids = _validate_poll_choices(
        payload.choice_ids,
        allow_multiple=poll.allow_multiple_choices,
    )
    available_choice_ids = {choice.id for choice in poll.choices}
    unknown_choice_ids = [choice_id for choice_id in selected_choice_ids if choice_id not in available_choice_ids]
    if unknown_choice_ids:
        raise NotFoundError("Poll choice not found.")

    existing_votes = await repository.list_votes_for_user(poll_id=poll.id, user_id=current_user_id)
    for vote in existing_votes:
        await repository.delete_vote(vote)

    for choice_id in selected_choice_ids:
        await repository.add_vote(
            PollVote(
                poll_id=poll.id,
                choice_id=choice_id,
                user_id=current_user_id,
            )
        )

    refreshed = await repository.get_by_id(poll.id)
    if refreshed is None:
        raise NotFoundError("Poll not found.")
    return _to_poll_read(refreshed, current_user_id=current_user_id)


async def get_poll_results(
    session: AsyncSession,
    poll_id: int,
    current_user_id: UUID,
) -> PollRead:
    repository = PollRepository(session)
    poll = await repository.get_by_id(poll_id)
    if poll is None:
        raise NotFoundError("Poll not found.")
    return _to_poll_read(poll, current_user_id=current_user_id)


async def list_feed(
    session: AsyncSession,
    current_user_id: UUID,
    item_type: str | None = None,
    include_drafts: bool = False,
    include_archived: bool = False,
) -> list[FeedItemRead]:
    normalized_item_type = item_type.strip().lower() if item_type else None
    if normalized_item_type not in {None, "announcement", "poll"}:
        raise ConflictError("Invalid feed item_type.")

    feed_items: list[tuple[str, object, object]] = []
    if normalized_item_type in {None, "announcement"}:
        if include_archived:
            announcement_statuses = ["archived"]
        else:
            announcement_statuses = ["published", "draft"] if include_drafts else ["published"]
        announcements = await list_announcements(session, statuses=announcement_statuses)
        for item in announcements:
            feed_items.append(("announcement", item, item.created_at))
    if normalized_item_type in {None, "poll"}:
        if include_archived:
            poll_statuses = ["archived"]
        else:
            poll_statuses = (
                ["published", "closed", "draft"]
                if include_drafts
                else ["published", "closed"]
            )
        polls = await PollRepository(session).list(statuses=poll_statuses)
        for item in polls:
            feed_items.append(("poll", item, item.created_at))

    feed_items.sort(key=lambda item: item[2], reverse=True)
    response: list[FeedItemRead] = []
    for kind, item, _created_at in feed_items:
        if kind == "announcement":
            response.append(
                FeedItemRead(
                    item_type="announcement",
                    announcement=AnnouncementRead.model_validate(item),
                )
            )
        else:
            response.append(
                FeedItemRead(
                    item_type="poll",
                    poll=_to_poll_read(item, current_user_id=current_user_id),  # type: ignore[arg-type]
                )
            )
    return response


async def list_shared_resources(
    session: AsyncSession,
    current_user_id: UUID,
    uploader_id: UUID | None = None,
    search: str | None = None,
) -> list[SharedResourceRead]:
    repository = SharedResourceRepository(session)
    resources = await repository.list_for_user(
        user_id=current_user_id,
        uploader_id=uploader_id,
        search=search,
    )
    visible_resources = [resource for resource in resources if _resource_can_be_seen_by(resource, current_user_id)]
    return [_to_shared_resource_read(resource) for resource in visible_resources]


async def list_shared_resource_shareable_users(
    session: AsyncSession,
    current_user_id: UUID,
    query: str | None = None,
) -> list[User]:
    repository = UserRepository(session)
    return await repository.list(
        query=query,
        active_only=True,
        exclude_user_id=current_user_id,
    )


async def create_shared_resource(
    session: AsyncSession,
    current_user_id: UUID,
    payload: SharedResourceCreateRequest,
) -> SharedResourceRead:
    user_repository = UserRepository(session)
    repository = SharedResourceRepository(session)

    shared_user_ids = _normalized_uuid_list(payload.shared_user_ids)
    confidential_user_ids = _normalized_uuid_list(payload.confidential_access_user_ids)

    for user_id in shared_user_ids + confidential_user_ids:
        if user_id == current_user_id:
            continue
        if await user_repository.get_by_id(user_id) is None:
            raise NotFoundError(f"User {user_id} not found.")

    if payload.is_confidential:
        invalid_confidential_ids = [
            user_id for user_id in confidential_user_ids if user_id not in shared_user_ids
        ]
        if invalid_confidential_ids:
            raise ConflictError(
                "Confidential access users must already be included in shared users."
            )

    item = SharedResource(
        uploader_id=current_user_id,
        resource_name=payload.resource_name.strip(),
        description=payload.description.strip() if payload.description else None,
        storage_key=payload.storage_key.strip(),
        original_filename=payload.original_filename.strip(),
        content_type=payload.content_type.strip() if payload.content_type else None,
        size_bytes=payload.size_bytes,
        is_confidential=payload.is_confidential,
    )
    created = await repository.create(item)

    for user_id in shared_user_ids:
        await repository.add_share(created.id, user_id)
    if payload.is_confidential:
        for user_id in confidential_user_ids:
            await repository.add_confidential_access(created.id, user_id)

    refreshed = await repository.get_by_id(created.id)
    if refreshed is None:
        raise NotFoundError("Shared resource not found.")
    await create_notifications_if_possible(
        session,
        recipient_ids=shared_user_ids,
        sender_id=current_user_id,
        content=f"A shared resource was added for you: {refreshed.resource_name}",
        url=f"/my/shared-resources?resource_id={refreshed.id}",
    )
    return _to_shared_resource_read(refreshed)


async def update_shared_resource(
    session: AsyncSession,
    resource_id: int,
    payload: SharedResourceUpdateRequest,
    current_user_id: UUID,
    is_staff: bool,
) -> SharedResourceRead:
    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_managed_by(resource, current_user_id, is_staff):
        raise PermissionDeniedError("Not enough permissions.")

    if payload.resource_name is not None:
        resource.resource_name = payload.resource_name.strip()
    if payload.description is not None:
        resource.description = payload.description.strip() if payload.description else None
    if payload.is_confidential is not None:
        resource.is_confidential = payload.is_confidential
        if not payload.is_confidential:
            await repository.clear_confidential_access(resource.id)
    await repository.save(resource)
    refreshed = await repository.get_by_id(resource.id)
    if refreshed is None:
        raise NotFoundError("Shared resource not found.")
    return _to_shared_resource_read(refreshed)


async def delete_shared_resource(
    session: AsyncSession,
    resource_id: int,
    current_user_id: UUID,
    is_staff: bool,
) -> None:
    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_managed_by(resource, current_user_id, is_staff):
        raise PermissionDeniedError("Not enough permissions.")
    delete_stored_resource_file(resource.storage_key)
    await repository.delete(resource)


async def create_shared_resource_from_upload(
    session: AsyncSession,
    current_user_id: UUID,
    uploaded_file: UploadFile,
    resource_name: str | None,
    description: str | None,
    shared_user_ids: list[UUID],
    is_confidential: bool,
    confidential_access_user_ids: list[UUID],
) -> SharedResourceRead:
    if not uploaded_file.filename:
        raise ConflictError("Uploaded file must have a filename.")

    stored_file = await save_uploaded_resource_file(
        uploader_id=current_user_id,
        uploaded_file=uploaded_file,
    )
    resolved_name = (resource_name or Path(stored_file.original_filename).stem).strip()
    if not resolved_name:
        resolved_name = "Untitled Resource"

    try:
        return await create_shared_resource(
            session=session,
            current_user_id=current_user_id,
            payload=SharedResourceCreateRequest(
                resource_name=resolved_name,
                description=description,
                storage_key=stored_file.storage_key,
                original_filename=stored_file.original_filename,
                content_type=stored_file.content_type,
                size_bytes=stored_file.size_bytes,
                shared_user_ids=shared_user_ids,
                is_confidential=is_confidential,
                confidential_access_user_ids=confidential_access_user_ids,
            ),
        )
    except Exception:
        delete_stored_resource_file(stored_file.storage_key)
        raise


async def get_shared_resource_download_details(
    session: AsyncSession,
    resource_id: int,
    current_user_id: UUID,
) -> str:
    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_seen_by(resource, current_user_id):
        raise PermissionDeniedError("Not enough permissions.")
    return get_stored_resource_download_url(
        resource.storage_key,
        original_filename=resource.original_filename,
        content_type=resource.content_type,
    )


async def add_shared_resource_user_access(
    session: AsyncSession,
    resource_id: int,
    user_id: UUID,
    current_user_id: UUID,
    is_staff: bool,
) -> SharedResourceRead:
    user_repository = UserRepository(session)
    if await user_repository.get_by_id(user_id) is None:
        raise NotFoundError("User not found.")

    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_managed_by(resource, current_user_id, is_staff):
        raise PermissionDeniedError("Not enough permissions.")

    if await repository.get_share(resource_id, user_id) is None:
        await repository.add_share(resource_id, user_id)

    refreshed = await repository.get_by_id(resource_id)
    if refreshed is None:
        raise NotFoundError("Shared resource not found.")
    await create_notification_if_possible(
        session,
        recipient_id=user_id,
        sender_id=current_user_id,
        content=f"You were granted access to shared resource: {refreshed.resource_name}",
        url=f"/my/shared-resources?resource_id={refreshed.id}",
    )
    return _to_shared_resource_read(refreshed)


async def replace_shared_resource_access(
    session: AsyncSession,
    resource_id: int,
    payload: SharedResourceAccessReplaceRequest,
    current_user_id: UUID,
    is_staff: bool,
) -> SharedResourceRead:
    user_repository = UserRepository(session)
    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_managed_by(resource, current_user_id, is_staff):
        raise PermissionDeniedError("Not enough permissions.")

    shared_user_ids = _normalized_uuid_list(payload.shared_user_ids)
    confidential_user_ids = _normalized_uuid_list(payload.confidential_access_user_ids)

    for user_id in shared_user_ids + confidential_user_ids:
        if user_id == current_user_id:
            continue
        if await user_repository.get_by_id(user_id) is None:
            raise NotFoundError(f"User {user_id} not found.")

    invalid_confidential_ids = [
        user_id for user_id in confidential_user_ids if user_id not in shared_user_ids
    ]
    if invalid_confidential_ids:
        raise ConflictError(
            "Confidential access users must already be included in shared users."
        )
    if confidential_user_ids and not resource.is_confidential:
        raise ConflictError("Resource is not confidential.")

    current_shared_ids = set(_resource_shared_user_ids(resource))
    current_confidential_ids = set(_resource_confidential_user_ids(resource))
    next_shared_ids = set(shared_user_ids)
    next_confidential_ids = set(confidential_user_ids)

    for user_id in current_confidential_ids - next_confidential_ids:
        access = await repository.get_confidential_access(resource_id, user_id)
        if access is not None:
            await repository.remove_confidential_access(access)

    for user_id in current_shared_ids - next_shared_ids:
        share = await repository.get_share(resource_id, user_id)
        if share is not None:
            await repository.remove_share(share)

    for user_id in next_shared_ids - current_shared_ids:
        await repository.add_share(resource_id, user_id)

    for user_id in next_confidential_ids - current_confidential_ids:
        await repository.add_confidential_access(resource_id, user_id)

    refreshed = await repository.get_by_id(resource_id)
    if refreshed is None:
        raise NotFoundError("Shared resource not found.")
    return _to_shared_resource_read(refreshed)


async def remove_shared_resource_user_access(
    session: AsyncSession,
    resource_id: int,
    user_id: UUID,
    current_user_id: UUID,
    is_staff: bool,
) -> SharedResourceRead:
    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_managed_by(resource, current_user_id, is_staff):
        raise PermissionDeniedError("Not enough permissions.")

    share = await repository.get_share(resource_id, user_id)
    if share is not None:
        await repository.remove_share(share)

    confidential_access = await repository.get_confidential_access(resource_id, user_id)
    if confidential_access is not None:
        await repository.remove_confidential_access(confidential_access)

    refreshed = await repository.get_by_id(resource_id)
    if refreshed is None:
        raise NotFoundError("Shared resource not found.")
    return _to_shared_resource_read(refreshed)


async def add_shared_resource_confidential_access(
    session: AsyncSession,
    resource_id: int,
    user_id: UUID,
    current_user_id: UUID,
    is_staff: bool,
) -> SharedResourceRead:
    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_managed_by(resource, current_user_id, is_staff):
        raise PermissionDeniedError("Not enough permissions.")
    if not resource.is_confidential:
        raise ConflictError("Resource is not confidential.")

    share = await repository.get_share(resource_id, user_id)
    if share is None:
        raise ConflictError("User must have shared access before confidential access.")

    if await repository.get_confidential_access(resource_id, user_id) is None:
        await repository.add_confidential_access(resource_id, user_id)

    refreshed = await repository.get_by_id(resource_id)
    if refreshed is None:
        raise NotFoundError("Shared resource not found.")
    await create_notification_if_possible(
        session,
        recipient_id=user_id,
        sender_id=current_user_id,
        content=(
            f"You were granted confidential access to shared resource: "
            f"{refreshed.resource_name}"
        ),
        url=f"/my/shared-resources?resource_id={refreshed.id}",
    )
    return _to_shared_resource_read(refreshed)


async def remove_shared_resource_confidential_access(
    session: AsyncSession,
    resource_id: int,
    user_id: UUID,
    current_user_id: UUID,
    is_staff: bool,
) -> SharedResourceRead:
    repository = SharedResourceRepository(session)
    resource = await repository.get_by_id(resource_id)
    if resource is None:
        raise NotFoundError("Shared resource not found.")
    if not _resource_can_be_managed_by(resource, current_user_id, is_staff):
        raise PermissionDeniedError("Not enough permissions.")

    access = await repository.get_confidential_access(resource_id, user_id)
    if access is not None:
        await repository.remove_confidential_access(access)

    refreshed = await repository.get_by_id(resource_id)
    if refreshed is None:
        raise NotFoundError("Shared resource not found.")
    return _to_shared_resource_read(refreshed)
