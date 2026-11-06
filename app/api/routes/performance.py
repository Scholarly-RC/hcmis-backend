from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session, require_staff_user
from app.core.capabilities import is_staff_user
from app.models.performance import Evaluation, Questionnaire, UserEvaluation
from app.models.user import User
from app.schemas.performance import (
    AnnouncementCreateRequest,
    AnnouncementRead,
    AnnouncementUpdateRequest,
    EvaluationAssignmentRequest,
    EvaluationCreateRequest,
    EvaluationRead,
    FeedItemRead,
    PollChoiceCreateRequest,
    PollRead,
    PollUpdateRequest,
    PollVoteSubmitRequest,
    PollCreateRequest,
    SharedResourceAccessReplaceRequest,
    SharedResourceAccessUpdateRequest,
    SharedResourceCreateRequest,
    SharedResourceRead,
    SharedResourceUpdateRequest,
    EvaluationSummaryRead,
    EvaluationUpdateRequest,
    QuestionnaireCreateRequest,
    QuestionnaireRead,
    QuestionnaireUpdateRequest,
    UserEvaluationCreateRequest,
    UserEvaluationAggregateRead,
    UserEvaluationRead,
    UserEvaluationUpdateRequest,
)
from app.schemas.user import UserRead
from app.services.performance import (
    add_poll_choice,
    add_shared_resource_confidential_access,
    add_shared_resource_user_access,
    archive_announcement,
    archive_poll,
    revert_announcement_to_draft,
    close_poll,
    create_announcement,
    create_evaluation,
    create_poll,
    create_questionnaire,
    create_shared_resource_from_upload,
    create_shared_resource,
    create_user_evaluation,
    assign_user_evaluation_evaluator,
    delete_shared_resource,
    delete_evaluation,
    delete_questionnaire,
    delete_user_evaluation,
    get_evaluation_summary,
    get_poll_results,
    get_shared_resource_download_details,
    list_announcements,
    list_feed,
    list_evaluations,
    list_polls,
    list_questionnaires,
    list_shared_resource_shareable_users,
    list_shared_resources,
    list_user_evaluations,
    get_user_evaluation_aggregate_summary,
    publish_announcement,
    publish_poll,
    reopen_poll,
    replace_shared_resource_access,
    remove_poll_choice,
    remove_shared_resource_confidential_access,
    remove_shared_resource_user_access,
    reset_evaluation,
    reset_user_evaluation,
    unassign_user_evaluation_evaluator,
    submit_poll_vote,
    submit_evaluation,
    toggle_user_evaluation_finalized,
    unarchive_announcement,
    unarchive_poll,
    update_announcement,
    update_poll,
    update_shared_resource,
    update_evaluation,
    update_questionnaire,
    update_user_evaluation,
)

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/feed", response_model=list[FeedItemRead])
async def read_feed(
    item_type: str | None = None,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[FeedItemRead]:
    is_staff = is_staff_user(current_user)
    return await list_feed(
        session=session,
        current_user_id=current_user.id,
        item_type=item_type,
        include_drafts=is_staff,
        include_archived=include_archived and is_staff,
    )


@router.get("/announcements", response_model=list[AnnouncementRead])
async def read_announcements(
    status: list[str] | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[AnnouncementRead]:
    items = await list_announcements(session, statuses=status)
    return [AnnouncementRead.model_validate(item) for item in items]


@router.post(
    "/announcements",
    response_model=AnnouncementRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_announcement(
    payload: AnnouncementCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> AnnouncementRead:
    item = await create_announcement(session, current_user.id, payload)
    return AnnouncementRead.model_validate(item)


@router.patch("/announcements/{announcement_id}", response_model=AnnouncementRead)
async def patch_announcement(
    announcement_id: int,
    payload: AnnouncementUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> AnnouncementRead:
    item = await update_announcement(session, announcement_id, payload)
    return AnnouncementRead.model_validate(item)


@router.post("/announcements/{announcement_id}/publish", response_model=AnnouncementRead)
async def publish_announcement_route(
    announcement_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> AnnouncementRead:
    item = await publish_announcement(session, announcement_id)
    return AnnouncementRead.model_validate(item)


@router.post("/announcements/{announcement_id}/archive", response_model=AnnouncementRead)
async def archive_announcement_route(
    announcement_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> AnnouncementRead:
    item = await archive_announcement(session, announcement_id)
    return AnnouncementRead.model_validate(item)


@router.post("/announcements/{announcement_id}/unarchive", response_model=AnnouncementRead)
async def unarchive_announcement_route(
    announcement_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> AnnouncementRead:
    item = await unarchive_announcement(session, announcement_id)
    return AnnouncementRead.model_validate(item)


@router.post("/announcements/{announcement_id}/draft", response_model=AnnouncementRead)
async def move_announcement_to_draft_route(
    announcement_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> AnnouncementRead:
    item = await revert_announcement_to_draft(session, announcement_id)
    return AnnouncementRead.model_validate(item)


@router.get("/polls", response_model=list[PollRead])
async def read_polls(
    status: list[str] | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[PollRead]:
    return await list_polls(
        session=session,
        current_user_id=current_user.id,
        statuses=status,
    )


@router.post(
    "/polls",
    response_model=PollRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_poll(
    payload: PollCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await create_poll(
        session=session,
        current_user_id=current_user.id,
        payload=payload,
    )


@router.patch("/polls/{poll_id}", response_model=PollRead)
async def patch_poll(
    poll_id: int,
    payload: PollUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await update_poll(session, poll_id, payload)


@router.post("/polls/{poll_id}/publish", response_model=PollRead)
async def publish_poll_route(
    poll_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await publish_poll(session, poll_id)


@router.post("/polls/{poll_id}/close", response_model=PollRead)
async def close_poll_route(
    poll_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await close_poll(session, poll_id)


@router.post("/polls/{poll_id}/reopen", response_model=PollRead)
async def reopen_poll_route(
    poll_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await reopen_poll(session, poll_id)


@router.post("/polls/{poll_id}/archive", response_model=PollRead)
async def archive_poll_route(
    poll_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await archive_poll(session, poll_id)


@router.post("/polls/{poll_id}/unarchive", response_model=PollRead)
async def unarchive_poll_route(
    poll_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await unarchive_poll(session, poll_id)


@router.post("/polls/{poll_id}/choices", response_model=PollRead)
async def post_poll_choice(
    poll_id: int,
    payload: PollChoiceCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await add_poll_choice(
        session=session,
        poll_id=poll_id,
        text=payload.text,
    )


@router.delete("/polls/{poll_id}/choices/{choice_id}", response_model=PollRead)
async def remove_poll_choice_route(
    poll_id: int,
    choice_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> PollRead:
    return await remove_poll_choice(
        session=session,
        poll_id=poll_id,
        choice_id=choice_id,
    )


@router.post("/polls/{poll_id}/votes", response_model=PollRead)
async def submit_poll_vote_route(
    poll_id: int,
    payload: PollVoteSubmitRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> PollRead:
    return await submit_poll_vote(
        session=session,
        poll_id=poll_id,
        current_user_id=current_user.id,
        payload=payload,
    )


@router.get("/polls/{poll_id}/results", response_model=PollRead)
async def read_poll_results(
    poll_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> PollRead:
    return await get_poll_results(
        session=session,
        poll_id=poll_id,
        current_user_id=current_user.id,
    )


@router.get("/questionnaires", response_model=list[QuestionnaireRead])
async def read_questionnaires(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[Questionnaire]:
    return await list_questionnaires(session)


@router.post(
    "/questionnaires",
    response_model=QuestionnaireRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_questionnaire(
    payload: QuestionnaireCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> Questionnaire:
    return await create_questionnaire(session, payload)


@router.patch("/questionnaires/{questionnaire_id}", response_model=QuestionnaireRead)
async def patch_questionnaire(
    questionnaire_id: int,
    payload: QuestionnaireUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> Questionnaire:
    return await update_questionnaire(session, questionnaire_id, payload)


@router.delete("/questionnaires/{questionnaire_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_questionnaire(
    questionnaire_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> None:
    await delete_questionnaire(session, questionnaire_id)


@router.get("/user-evaluations", response_model=list[UserEvaluationRead])
async def read_user_evaluations(
    evaluatee_id: UUID | None = None,
    questionnaire_id: int | None = None,
    quarter: str | None = None,
    year: int | None = None,
    is_finalized: bool | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[UserEvaluation]:
    return await list_user_evaluations(
        session,
        evaluatee_id=evaluatee_id,
        questionnaire_id=questionnaire_id,
        quarter=quarter,
        year=year,
        is_finalized=is_finalized,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.post(
    "/user-evaluations",
    response_model=UserEvaluationRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_user_evaluation(
    payload: UserEvaluationCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> UserEvaluation:
    return await create_user_evaluation(session, payload)


@router.patch("/user-evaluations/{user_evaluation_id}", response_model=UserEvaluationRead)
async def patch_user_evaluation(
    user_evaluation_id: int,
    payload: UserEvaluationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> UserEvaluation:
    return await update_user_evaluation(session, user_evaluation_id, payload)


@router.post("/user-evaluations/{user_evaluation_id}/finalize-toggle", response_model=UserEvaluationRead)
async def toggle_user_evaluation(
    user_evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> UserEvaluation:
    return await toggle_user_evaluation_finalized(session, user_evaluation_id)


@router.post("/user-evaluations/{user_evaluation_id}/reset", response_model=UserEvaluationRead)
async def reset_user_evaluation_route(
    user_evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> UserEvaluation:
    return await reset_user_evaluation(session, user_evaluation_id)


@router.delete("/user-evaluations/{user_evaluation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_evaluation(
    user_evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> None:
    await delete_user_evaluation(session, user_evaluation_id)


@router.get("/user-evaluations/{user_evaluation_id}/evaluations", response_model=list[EvaluationRead])
async def read_evaluations(
    user_evaluation_id: int,
    evaluator_id: UUID | None = None,
    is_submitted: bool | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[Evaluation]:
    return await list_evaluations(
        session,
        user_evaluation_id=user_evaluation_id,
        evaluator_id=evaluator_id,
        is_submitted=is_submitted,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.get("/evaluations", response_model=list[EvaluationRead])
async def read_all_evaluations(
    user_evaluation_id: int | None = None,
    evaluator_id: UUID | None = None,
    is_submitted: bool | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[Evaluation]:
    return await list_evaluations(
        session,
        user_evaluation_id=user_evaluation_id,
        evaluator_id=evaluator_id,
        is_submitted=is_submitted,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.post(
    "/user-evaluations/{user_evaluation_id}/evaluations",
    response_model=EvaluationRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_evaluation(
    user_evaluation_id: int,
    payload: EvaluationCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Evaluation:
    return await create_evaluation(
        session,
        user_evaluation_id,
        current_user.id,
        payload,
        is_staff=is_staff_user(current_user),
    )


@router.post(
    "/user-evaluations/{user_evaluation_id}/assignments",
    response_model=EvaluationRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_evaluator(
    user_evaluation_id: int,
    payload: EvaluationAssignmentRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> Evaluation:
    return await assign_user_evaluation_evaluator(
        session=session,
        user_evaluation_id=user_evaluation_id,
        payload=payload,
    )


@router.delete(
    "/user-evaluations/{user_evaluation_id}/assignments/{evaluator_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unassign_evaluator(
    user_evaluation_id: int,
    evaluator_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_staff_user),
) -> None:
    await unassign_user_evaluation_evaluator(
        session=session,
        user_evaluation_id=user_evaluation_id,
        evaluator_id=evaluator_id,
    )


@router.patch("/evaluations/{evaluation_id}", response_model=EvaluationRead)
async def patch_evaluation(
    evaluation_id: int,
    payload: EvaluationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Evaluation:
    return await update_evaluation(
        session,
        evaluation_id,
        payload,
        current_user_id=current_user.id,
    )


@router.post("/evaluations/{evaluation_id}/submit", response_model=EvaluationRead)
async def submit_evaluation_route(
    evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Evaluation:
    return await submit_evaluation(
        session,
        evaluation_id,
        current_user_id=current_user.id,
    )


@router.post("/evaluations/{evaluation_id}/reset", response_model=EvaluationRead)
async def reset_evaluation_route(
    evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Evaluation:
    return await reset_evaluation(
        session,
        evaluation_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.get("/evaluations/{evaluation_id}/summary", response_model=EvaluationSummaryRead)
async def read_evaluation_summary(
    evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> EvaluationSummaryRead:
    return await get_evaluation_summary(
        session,
        evaluation_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.delete("/evaluations/{evaluation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_evaluation(
    evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> None:
    await delete_evaluation(
        session,
        evaluation_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.get(
    "/user-evaluations/{user_evaluation_id}/aggregate-summary",
    response_model=UserEvaluationAggregateRead,
)
async def read_user_evaluation_aggregate_summary(
    user_evaluation_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> UserEvaluationAggregateRead:
    return await get_user_evaluation_aggregate_summary(
        session=session,
        user_evaluation_id=user_evaluation_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.get("/shared-resources", response_model=list[SharedResourceRead])
async def read_shared_resources(
    uploader_id: UUID | None = None,
    search: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[SharedResourceRead]:
    return await list_shared_resources(
        session,
        current_user_id=current_user.id,
        uploader_id=uploader_id,
        search=search,
    )


@router.get("/shared-resources/shareable-users", response_model=list[UserRead])
async def read_shared_resource_shareable_users(
    q: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    return await list_shared_resource_shareable_users(
        session=session,
        current_user_id=current_user.id,
        query=q,
    )


@router.post(
    "/shared-resources",
    response_model=SharedResourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_shared_resource(
    payload: SharedResourceCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await create_shared_resource(
        session,
        current_user_id=current_user.id,
        payload=payload,
    )


@router.post(
    "/shared-resources/upload",
    response_model=SharedResourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_shared_resource(
    uploaded_file: UploadFile = File(...),
    resource_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    shared_user_ids: list[UUID] = Form(default=[]),
    is_confidential: bool = Form(default=False),
    confidential_access_user_ids: list[UUID] = Form(default=[]),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await create_shared_resource_from_upload(
        session=session,
        current_user_id=current_user.id,
        uploaded_file=uploaded_file,
        resource_name=resource_name,
        description=description,
        shared_user_ids=shared_user_ids,
        is_confidential=is_confidential,
        confidential_access_user_ids=confidential_access_user_ids,
    )


@router.patch("/shared-resources/{resource_id}", response_model=SharedResourceRead)
async def patch_shared_resource(
    resource_id: int,
    payload: SharedResourceUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await update_shared_resource(
        session,
        resource_id=resource_id,
        payload=payload,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.delete("/shared-resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_shared_resource(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> None:
    await delete_shared_resource(
        session,
        resource_id=resource_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.get("/shared-resources/{resource_id}/download")
async def download_shared_resource(
    resource_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> RedirectResponse:
    download_url = await get_shared_resource_download_details(
        session=session,
        resource_id=resource_id,
        current_user_id=current_user.id,
    )
    return RedirectResponse(url=download_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post("/shared-resources/{resource_id}/shares", response_model=SharedResourceRead)
async def add_share_access(
    resource_id: int,
    payload: SharedResourceAccessUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await add_shared_resource_user_access(
        session,
        resource_id=resource_id,
        user_id=payload.user_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.put("/shared-resources/{resource_id}/access", response_model=SharedResourceRead)
async def replace_access(
    resource_id: int,
    payload: SharedResourceAccessReplaceRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await replace_shared_resource_access(
        session=session,
        resource_id=resource_id,
        payload=payload,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.delete("/shared-resources/{resource_id}/shares/{user_id}", response_model=SharedResourceRead)
async def remove_share_access(
    resource_id: int,
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await remove_shared_resource_user_access(
        session,
        resource_id=resource_id,
        user_id=user_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.post("/shared-resources/{resource_id}/confidential-access", response_model=SharedResourceRead)
async def add_confidential_access(
    resource_id: int,
    payload: SharedResourceAccessUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await add_shared_resource_confidential_access(
        session,
        resource_id=resource_id,
        user_id=payload.user_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )


@router.delete(
    "/shared-resources/{resource_id}/confidential-access/{user_id}",
    response_model=SharedResourceRead,
)
async def remove_confidential_access(
    resource_id: int,
    user_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> SharedResourceRead:
    return await remove_shared_resource_confidential_access(
        session,
        resource_id=resource_id,
        user_id=user_id,
        current_user_id=current_user.id,
        is_staff=is_staff_user(current_user),
    )
