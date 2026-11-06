import anyio
import pytest
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, PermissionDeniedError
from app.core.time import utc_now
from app.models.department import Department
from app.models.performance import (
    Announcement,
    Evaluation,
    Poll,
    PollChoice,
    PollVote,
    Questionnaire,
    SharedResource,
    SharedResourceConfidentialAccess,
    SharedResourceShare,
    UserEvaluation,
)
from app.models.user import User
from app.schemas.performance import (
    AnnouncementCreateRequest,
    AnnouncementUpdateRequest,
    EvaluationAssignmentRequest,
    EvaluationCreateRequest,
    EvaluationUpdateRequest,
    PollCreateRequest,
    PollVoteSubmitRequest,
    PollChoiceCreateRequest,
    SharedResourceAccessReplaceRequest,
    QuestionnaireCreateRequest,
    SharedResourceCreateRequest,
    SharedResourceUpdateRequest,
    UserEvaluationCreateRequest,
    UserEvaluationUpdateRequest,
)
from app.services import performance as performance_service


class FakeUserRepository:
    users: dict[UUID, User] = {}

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, user_id: UUID):
        return self.users.get(user_id)


class FakeQuestionnaireRepository:
    items: dict[int, Questionnaire] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, include_inactive: bool = False):
        items = list(self.items.values())
        if not include_inactive:
            items = [item for item in items if item.is_active]
        return items

    async def get_by_id(self, questionnaire_id: int):
        return self.items.get(questionnaire_id)

    async def get_by_code(self, code: str):
        for item in self.items.values():
            if item.code == code.upper():
                return item
        return None

    async def create(self, questionnaire: Questionnaire):
        questionnaire.id = FakeQuestionnaireRepository.next_id
        FakeQuestionnaireRepository.next_id += 1
        questionnaire.created_at = questionnaire.created_at or utc_now()
        questionnaire.updated_at = questionnaire.updated_at or utc_now()
        FakeQuestionnaireRepository.items[questionnaire.id] = questionnaire
        return questionnaire

    async def save(self, questionnaire: Questionnaire):
        questionnaire.updated_at = utc_now()
        self.items[questionnaire.id] = questionnaire
        return questionnaire

    async def delete(self, questionnaire: Questionnaire):
        self.items.pop(questionnaire.id, None)


class FakeUserEvaluationRepository:
    items: dict[int, UserEvaluation] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(
        self,
        evaluatee_id=None,
        questionnaire_id=None,
        quarter=None,
        year=None,
        is_finalized=None,
        evaluator_id=None,
        is_submitted=None,
    ):
        items = list(self.items.values())
        if evaluatee_id is not None:
            items = [item for item in items if item.evaluatee_id == evaluatee_id]
        if questionnaire_id is not None:
            items = [item for item in items if item.questionnaire_id == questionnaire_id]
        if quarter is not None:
            items = [item for item in items if item.quarter == quarter]
        if year is not None:
            items = [item for item in items if item.year == year]
        if is_finalized is not None:
            items = [item for item in items if item.is_finalized == is_finalized]
        if evaluator_id is not None or is_submitted is not None:
            items = [
                item
                for item in items
                if any(
                    (evaluator_id is None or evaluation.evaluator_id == evaluator_id)
                    and (
                        is_submitted is None
                        or (evaluation.date_submitted is not None) == is_submitted
                    )
                    for evaluation in item.evaluations
                )
            ]
        return items

    async def get_by_id(self, user_evaluation_id: int):
        return self.items.get(user_evaluation_id)

    async def get_by_identity(self, evaluatee_id: UUID, questionnaire_id: int, quarter: str, year: int):
        for item in self.items.values():
            if (
                item.evaluatee_id == evaluatee_id
                and item.questionnaire_id == questionnaire_id
                and item.quarter == quarter
                and item.year == year
            ):
                return item
        return None

    async def create(self, item: UserEvaluation):
        item.id = self.next_id
        self.next_id += 1
        item.created_at = item.created_at or utc_now()
        item.updated_at = item.updated_at or utc_now()
        item.evaluatee = FakeUserRepository.users[item.evaluatee_id]
        item.questionnaire = FakeQuestionnaireRepository.items[item.questionnaire_id]
        item.evaluations = []
        self.items[item.id] = item
        return item

    async def save(self, item: UserEvaluation):
        item.updated_at = utc_now()
        self.items[item.id] = item
        return item

    async def delete(self, item: UserEvaluation):
        self.items.pop(item.id, None)


class FakeEvaluationRepository:
    items: dict[int, Evaluation] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, user_evaluation_id=None, evaluator_id=None, is_submitted=None):
        items = list(self.items.values())
        if user_evaluation_id is not None:
            items = [item for item in items if item.user_evaluation_id == user_evaluation_id]
        if evaluator_id is not None:
            items = [item for item in items if item.evaluator_id == evaluator_id]
        if is_submitted is not None:
            items = [item for item in items if (item.date_submitted is not None) == is_submitted]
        return items

    async def get_by_id(self, evaluation_id: int):
        return self.items.get(evaluation_id)

    async def get_by_identity(self, user_evaluation_id: int, evaluator_id: UUID):
        for item in self.items.values():
            if item.user_evaluation_id == user_evaluation_id and item.evaluator_id == evaluator_id:
                return item
        return None

    async def create(self, item: Evaluation):
        item.id = type(self).next_id
        type(self).next_id += 1
        item.created_at = item.created_at or utc_now()
        item.updated_at = item.updated_at or utc_now()
        item.evaluator = FakeUserRepository.users[item.evaluator_id]
        item.user_evaluation = FakeUserEvaluationRepository.items[item.user_evaluation_id]
        item.questionnaire = FakeQuestionnaireRepository.items[item.questionnaire_id]
        self.items[item.id] = item
        FakeUserEvaluationRepository.items[item.user_evaluation_id].evaluations.append(item)
        return item

    async def save(self, item: Evaluation):
        item.updated_at = utc_now()
        self.items[item.id] = item
        return item

    async def delete(self, item: Evaluation):
        self.items.pop(item.id, None)


class FakeAnnouncementRepository:
    items: dict[int, Announcement] = {}
    next_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, statuses=None):
        items = list(self.items.values())
        if statuses:
            items = [item for item in items if item.status in statuses]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def get_by_id(self, announcement_id: int):
        return self.items.get(announcement_id)

    async def create(self, item: Announcement):
        item.id = self.next_id
        self.next_id += 1
        item.created_at = item.created_at or utc_now()
        item.updated_at = item.updated_at or utc_now()
        self.items[item.id] = item
        return item

    async def save(self, item: Announcement):
        item.updated_at = utc_now()
        self.items[item.id] = item
        return item

    async def delete(self, item: Announcement):
        self.items.pop(item.id, None)


class FakePollRepository:
    polls: dict[int, Poll] = {}
    choices: dict[int, PollChoice] = {}
    votes: dict[int, PollVote] = {}
    next_poll_id = 1
    next_choice_id = 1
    next_vote_id = 1

    def __init__(self, session):
        self.session = session

    async def list(self, statuses=None):
        items = list(self.polls.values())
        if statuses:
            items = [item for item in items if item.status in statuses]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def get_by_id(self, poll_id: int):
        return self.polls.get(poll_id)

    async def create(self, item: Poll):
        item.id = self.next_poll_id
        self.next_poll_id += 1
        item.created_at = item.created_at or utc_now()
        item.updated_at = item.updated_at or utc_now()
        item.choices = []
        item.votes = []
        self.polls[item.id] = item
        return item

    async def save(self, item: Poll):
        item.updated_at = utc_now()
        self.polls[item.id] = item
        return item

    async def delete(self, item: Poll):
        self.polls.pop(item.id, None)

    async def add_choice(self, item: PollChoice):
        item.id = self.next_choice_id
        self.next_choice_id += 1
        item.created_at = item.created_at or utc_now()
        self.choices[item.id] = item
        poll = self.polls[item.poll_id]
        poll.choices.append(item)
        return item

    async def delete_choice(self, item: PollChoice):
        poll = self.polls[item.poll_id]
        poll.choices = [choice for choice in poll.choices if choice.id != item.id]
        poll.votes = [vote for vote in poll.votes if vote.choice_id != item.id]
        for vote_id, vote in list(self.votes.items()):
            if vote.choice_id == item.id:
                self.votes.pop(vote_id, None)
        self.choices.pop(item.id, None)

    async def list_votes_for_user(self, poll_id: int, user_id: UUID):
        poll = self.polls[poll_id]
        return [vote for vote in poll.votes if vote.user_id == user_id]

    async def add_vote(self, item: PollVote):
        item.id = self.next_vote_id
        self.next_vote_id += 1
        item.created_at = item.created_at or utc_now()
        self.votes[item.id] = item
        poll = self.polls[item.poll_id]
        poll.votes.append(item)
        return item

    async def delete_vote(self, item: PollVote):
        poll = self.polls[item.poll_id]
        poll.votes = [vote for vote in poll.votes if vote.id != item.id]
        self.votes.pop(item.id, None)


class FakeSharedResourceRepository:
    items: dict[int, SharedResource] = {}
    next_id = 1
    next_access_id = 1

    def __init__(self, session):
        self.session = session

    async def list_for_user(
        self, user_id: UUID, uploader_id: UUID | None = None, search: str | None = None
    ):
        items = []
        for item in self.items.values():
            shared_user_ids = {share.user_id for share in item.shares}
            if item.uploader_id == user_id or user_id in shared_user_ids:
                items.append(item)
        if uploader_id is not None:
            items = [item for item in items if item.uploader_id == uploader_id]
        if search:
            lowered = search.lower()
            items = [item for item in items if lowered in item.resource_name.lower()]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    async def get_by_id(self, resource_id: int):
        return self.items.get(resource_id)

    async def create(self, item: SharedResource):
        item.id = self.next_id
        self.next_id += 1
        item.created_at = item.created_at or utc_now()
        item.updated_at = item.updated_at or utc_now()
        item.shares = []
        item.confidential_access = []
        self.items[item.id] = item
        return item

    async def save(self, item: SharedResource):
        item.updated_at = utc_now()
        self.items[item.id] = item
        return item

    async def delete(self, item: SharedResource):
        self.items.pop(item.id, None)

    async def get_share(self, resource_id: int, user_id: UUID):
        item = self.items.get(resource_id)
        if item is None:
            return None
        for share in item.shares:
            if share.user_id == user_id:
                return share
        return None

    async def add_share(self, resource_id: int, user_id: UUID):
        item = self.items[resource_id]
        share = SharedResourceShare(
            id=self.next_access_id,
            resource_id=resource_id,
            user_id=user_id,
            created_at=utc_now(),
        )
        self.next_access_id += 1
        item.shares.append(share)
        return share

    async def remove_share(self, share):
        item = self.items[share.resource_id]
        item.shares = [current for current in item.shares if current.id != share.id]

    async def get_confidential_access(self, resource_id: int, user_id: UUID):
        item = self.items.get(resource_id)
        if item is None:
            return None
        for access in item.confidential_access:
            if access.user_id == user_id:
                return access
        return None

    async def add_confidential_access(self, resource_id: int, user_id: UUID):
        item = self.items[resource_id]
        access = SharedResourceConfidentialAccess(
            id=self.next_access_id,
            resource_id=resource_id,
            user_id=user_id,
            created_at=utc_now(),
        )
        self.next_access_id += 1
        item.confidential_access.append(access)
        return access

    async def remove_confidential_access(self, access):
        item = self.items[access.resource_id]
        item.confidential_access = [
            current for current in item.confidential_access if current.id != access.id
        ]

    async def clear_confidential_access(self, resource_id: int):
        item = self.items.get(resource_id)
        if item is not None:
            item.confidential_access = []


def _reset():
    FakeUserRepository.users = {}
    FakeQuestionnaireRepository.items = {}
    FakeQuestionnaireRepository.next_id = 1
    FakeUserEvaluationRepository.items = {}
    FakeUserEvaluationRepository.next_id = 1
    FakeEvaluationRepository.items = {}
    FakeEvaluationRepository.next_id = 1
    FakeAnnouncementRepository.items = {}
    FakeAnnouncementRepository.next_id = 1
    FakePollRepository.polls = {}
    FakePollRepository.choices = {}
    FakePollRepository.votes = {}
    FakePollRepository.next_poll_id = 1
    FakePollRepository.next_choice_id = 1
    FakePollRepository.next_vote_id = 1
    FakeSharedResourceRepository.items = {}
    FakeSharedResourceRepository.next_id = 1
    FakeSharedResourceRepository.next_access_id = 1


def _seed():
    dept = Department(id=1, name="Operations", code="OPS", is_active=True, workweek=[])
    user = User(
        id=UUID(int=1),
        email="employee@example.com",
        password_hash="hashed",
        first_name="Employee",
        last_name="One",
        department_id=1,
        is_active=True,
        is_superuser=False,
        can_modify_shift=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    user.department = dept
    peer = User(
        id=UUID(int=2),
        email="peer@example.com",
        password_hash="hashed",
        first_name="Peer",
        last_name="Two",
        department_id=1,
        is_active=True,
        is_superuser=False,
        can_modify_shift=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    peer.department = dept
    FakeUserRepository.users[UUID(int=1)] = user
    FakeUserRepository.users[UUID(int=2)] = peer


def test_questionnaire_and_user_evaluation_flow(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="pe-2026",
            title="Performance Evaluation 2026",
            content={
                "questionnaire_content": [
                    {
                        "domain_number": "1",
                        "questions": [
                            {"indicator_number": "1", "rating": None},
                            {"indicator_number": "2", "rating": None},
                        ],
                    }
                ]
            },
        ),
    )
    assert questionnaire.code == "PE-2026"

    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    assert user_evaluation.evaluatee_id == UUID(int=1)
    assert user_evaluation.is_finalized is False

    anyio.run(
        performance_service.assign_user_evaluation_evaluator,
        cast(AsyncSession, object()),
        user_evaluation.id,
        EvaluationAssignmentRequest(evaluator_id=UUID(int=2)),
    )
    finalized = anyio.run(
        performance_service.toggle_user_evaluation_finalized,
        cast(AsyncSession, object()),
        user_evaluation.id,
    )
    assert finalized.is_finalized is True
    assert any(evaluation.evaluator_id == UUID(int=1) for evaluation in finalized.evaluations)
    assert any(evaluation.evaluator_id == UUID(int=2) for evaluation in finalized.evaluations)


def test_peer_assignment_notifies_only_when_cycle_is_finalized(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    sent_notifications: list[dict[str, object]] = []

    async def fake_create_notifications_if_possible(
        session,
        recipient_ids,
        content,
        url,
        sender_id=None,
    ):
        sent_notifications.append(
            {
                "recipient_ids": list(recipient_ids),
                "content": content,
                "url": url,
                "sender_id": sender_id,
            }
        )

    async def fake_create_notification_if_possible(*args, **kwargs):
        sent_notifications.append({"single": True})

    monkeypatch.setattr(
        performance_service,
        "create_notifications_if_possible",
        fake_create_notifications_if_possible,
    )
    monkeypatch.setattr(
        performance_service,
        "create_notification_if_possible",
        fake_create_notification_if_possible,
    )

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="pe-2026",
            title="Performance Evaluation 2026",
            content={
                "questionnaire_content": [
                    {
                        "domain_number": "1",
                        "questions": [{"indicator_number": "1", "rating": None}],
                    }
                ]
            },
        ),
    )

    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )

    anyio.run(
        performance_service.assign_user_evaluation_evaluator,
        cast(AsyncSession, object()),
        user_evaluation.id,
        EvaluationAssignmentRequest(evaluator_id=UUID(int=2)),
    )
    assert sent_notifications == []

    anyio.run(
        performance_service.toggle_user_evaluation_finalized,
        cast(AsyncSession, object()),
        user_evaluation.id,
    )

    assert len(sent_notifications) == 1
    assert sent_notifications[0]["recipient_ids"] == [UUID(int=2)]
    assert sent_notifications[0]["url"] == f"/performance-evaluations?cycle_id={user_evaluation.id}"
    assert "You were assigned to evaluate Employee One for QFQ 2026." in cast(
        str, sent_notifications[0]["content"]
    )


def test_evaluation_summary_and_reset(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="PE-2026",
            title="Performance Evaluation 2026",
            content={
                "questionnaire_content": [
                    {
                        "domain_number": "1",
                        "questions": [
                            {"indicator_number": "1", "rating": None},
                            {"indicator_number": "2", "rating": None},
                        ],
                    }
                ]
            },
        ),
    )
    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    anyio.run(
        performance_service.assign_user_evaluation_evaluator,
        cast(AsyncSession, object()),
        user_evaluation.id,
        EvaluationAssignmentRequest(evaluator_id=UUID(int=2)),
    )
    anyio.run(
        performance_service.toggle_user_evaluation_finalized,
        cast(AsyncSession, object()),
        user_evaluation.id,
    )

    evaluation = anyio.run(
        performance_service.create_evaluation,
        cast(AsyncSession, object()),
        user_evaluation.id,
        UUID(int=2),
        EvaluationCreateRequest(
            content_data=[
                {
                    "domain_number": "1",
                    "questions": [
                        {"indicator_number": "1", "rating": 3},
                        {"indicator_number": "2", "rating": 5},
                    ],
                }
            ],
        ),
    )
    updated = anyio.run(
        performance_service.update_evaluation,
        cast(AsyncSession, object()),
        evaluation.id,
        EvaluationUpdateRequest(positive_feedback="Good", improvement_suggestion="Keep going"),
        UUID(int=2),
    )
    assert updated.positive_feedback == "Good"

    submitted = anyio.run(
        performance_service.submit_evaluation,
        cast(AsyncSession, object()),
        evaluation.id,
        UUID(int=2),
    )
    assert submitted.date_submitted is not None

    summary = anyio.run(
        performance_service.get_evaluation_summary,
        cast(AsyncSession, object()),
        evaluation.id,
        UUID(int=2),
        False,
    )
    assert summary.answered_question_count == 2
    assert summary.question_count == 2
    assert summary.overall_mean == 4.0
    assert summary.self_evaluation is False

    reset = anyio.run(
        performance_service.reset_evaluation,
        cast(AsyncSession, object()),
        evaluation.id,
        UUID(int=2),
        False,
    )
    assert reset.date_submitted is None
    assert reset.positive_feedback is None


def test_user_evaluation_enforces_employee_vs_administrator_questionnaire(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    employee_user = FakeUserRepository.users[UUID(int=1)]
    employee_user.role = "EMP"
    non_employee_user = FakeUserRepository.users[UUID(int=2)]
    non_employee_user.role = "HR"

    employee_questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="NIMER-EES",
            title="Employee Tool",
            content={"questionnaire_content": [{"domain_number": "1", "questions": []}]},
        ),
    )
    admin_questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="NIMER-NAPES",
            title="Admin Tool",
            content={"questionnaire_content": [{"domain_number": "1", "questions": []}]},
        ),
    )

    employee_cycle = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=employee_user.id,
            questionnaire_id=employee_questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    assert employee_cycle.questionnaire_id == employee_questionnaire.id

    non_employee_cycle = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=non_employee_user.id,
            questionnaire_id=admin_questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    assert non_employee_cycle.questionnaire_id == admin_questionnaire.id

    with pytest.raises(
        ConflictError,
        match="Employees must use the employee questionnaire",
    ):
        anyio.run(
            performance_service.create_user_evaluation,
            cast(AsyncSession, object()),
            UserEvaluationCreateRequest(
                evaluatee_id=employee_user.id,
                questionnaire_id=admin_questionnaire.id,
                quarter="SQ",
                year=2026,
            ),
        )

    with pytest.raises(
        ConflictError,
        match="Non-employees must use the administrator questionnaire",
    ):
        anyio.run(
            performance_service.create_user_evaluation,
            cast(AsyncSession, object()),
            UserEvaluationCreateRequest(
                evaluatee_id=non_employee_user.id,
                questionnaire_id=employee_questionnaire.id,
                quarter="SQ",
                year=2026,
            ),
        )


def test_update_user_evaluation_enforces_questionnaire_role_match(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    employee_user = FakeUserRepository.users[UUID(int=1)]
    employee_user.role = "EMP"

    employee_questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="NIMER-EES",
            title="Employee Tool",
            content={"questionnaire_content": [{"domain_number": "1", "questions": []}]},
        ),
    )
    admin_questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="NIMER-NAPES",
            title="Admin Tool",
            content={"questionnaire_content": [{"domain_number": "1", "questions": []}]},
        ),
    )

    employee_cycle = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=employee_user.id,
            questionnaire_id=employee_questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )

    with pytest.raises(
        ConflictError,
        match="Employees must use the employee questionnaire",
    ):
        anyio.run(
            performance_service.update_user_evaluation,
            cast(AsyncSession, object()),
            employee_cycle.id,
            UserEvaluationUpdateRequest(questionnaire_id=admin_questionnaire.id),
        )

def test_announcement_lifecycle_and_feed(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "AnnouncementRepository", FakeAnnouncementRepository)
    monkeypatch.setattr(performance_service, "PollRepository", FakePollRepository)

    draft = anyio.run(
        performance_service.create_announcement,
        cast(AsyncSession, object()),
        UUID(int=1),
        AnnouncementCreateRequest(
            title="System maintenance",
            summary="Night maintenance",
            content="Services are unavailable from 9PM to 10PM.",
        ),
    )
    assert draft.status == "draft"

    published = anyio.run(
        performance_service.publish_announcement,
        cast(AsyncSession, object()),
        draft.id,
    )
    assert published.status == "published"
    assert published.published_at is not None

    updated = anyio.run(
        performance_service.update_announcement,
        cast(AsyncSession, object()),
        draft.id,
        AnnouncementUpdateRequest(summary="Updated summary"),
    )
    assert updated.summary == "Updated summary"

    feed = anyio.run(
        performance_service.list_feed,
        cast(AsyncSession, object()),
        UUID(int=2),
        None,
    )
    assert len(feed) == 1
    assert feed[0].item_type == "announcement"
    assert feed[0].announcement is not None
    assert feed[0].announcement.title == "System maintenance"


def test_feed_includes_drafts_when_requested(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "AnnouncementRepository", FakeAnnouncementRepository)
    monkeypatch.setattr(performance_service, "PollRepository", FakePollRepository)

    announcement = anyio.run(
        performance_service.create_announcement,
        cast(AsyncSession, object()),
        UUID(int=1),
        AnnouncementCreateRequest(
            title="Draft announcement",
            summary="internal",
            content="Draft-only message.",
        ),
    )
    assert announcement.status == "draft"

    poll = anyio.run(
        performance_service.create_poll,
        cast(AsyncSession, object()),
        UUID(int=1),
        PollCreateRequest(
            question="Draft poll?",
            choices=[
                PollChoiceCreateRequest(text="Yes"),
                PollChoiceCreateRequest(text="No"),
            ],
        ),
    )
    assert poll.status == "draft"

    staff_feed = anyio.run(
        performance_service.list_feed,
        cast(AsyncSession, object()),
        UUID(int=1),
        None,
        True,
    )
    assert len(staff_feed) == 2
    assert {item.item_type for item in staff_feed} == {"announcement", "poll"}

    non_staff_feed = anyio.run(
        performance_service.list_feed,
        cast(AsyncSession, object()),
        UUID(int=2),
        None,
        False,
    )
    assert non_staff_feed == []

    archived_feed = anyio.run(
        performance_service.list_feed,
        cast(AsyncSession, object()),
        UUID(int=1),
        None,
        True,
        True,
    )
    assert archived_feed == []


def test_unarchive_and_move_to_draft_workflow(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "AnnouncementRepository", FakeAnnouncementRepository)
    monkeypatch.setattr(performance_service, "PollRepository", FakePollRepository)

    announcement = anyio.run(
        performance_service.create_announcement,
        cast(AsyncSession, object()),
        UUID(int=1),
        AnnouncementCreateRequest(
            title="Release notes",
            summary="v1.2",
            content="New release details.",
        ),
    )
    published_announcement = anyio.run(
        performance_service.publish_announcement,
        cast(AsyncSession, object()),
        announcement.id,
    )
    assert published_announcement.status == "published"

    archived_announcement = anyio.run(
        performance_service.archive_announcement,
        cast(AsyncSession, object()),
        announcement.id,
    )
    assert archived_announcement.status == "archived"

    restored_announcement = anyio.run(
        performance_service.unarchive_announcement,
        cast(AsyncSession, object()),
        announcement.id,
    )
    assert restored_announcement.status == "published"

    draft_announcement = anyio.run(
        performance_service.revert_announcement_to_draft,
        cast(AsyncSession, object()),
        announcement.id,
    )
    assert draft_announcement.status == "draft"
    assert draft_announcement.published_at is None
    re_archived_announcement = anyio.run(
        performance_service.archive_announcement,
        cast(AsyncSession, object()),
        announcement.id,
    )
    assert re_archived_announcement.status == "archived"

    poll = anyio.run(
        performance_service.create_poll,
        cast(AsyncSession, object()),
        UUID(int=1),
        PollCreateRequest(
            question="Deploy now?",
            choices=[
                PollChoiceCreateRequest(text="Go"),
                PollChoiceCreateRequest(text="Wait"),
            ],
        ),
    )
    published_poll = anyio.run(
        performance_service.publish_poll,
        cast(AsyncSession, object()),
        poll.id,
    )
    assert published_poll.status == "published"

    closed_poll = anyio.run(
        performance_service.close_poll,
        cast(AsyncSession, object()),
        poll.id,
    )
    assert closed_poll.status == "closed"

    reopened_poll = anyio.run(
        performance_service.reopen_poll,
        cast(AsyncSession, object()),
        poll.id,
    )
    assert reopened_poll.status == "published"
    assert reopened_poll.closed_at is None

    reclosed_poll = anyio.run(
        performance_service.close_poll,
        cast(AsyncSession, object()),
        poll.id,
    )
    assert reclosed_poll.status == "closed"

    archived_poll = anyio.run(
        performance_service.archive_poll,
        cast(AsyncSession, object()),
        poll.id,
    )
    assert archived_poll.status == "archived"

    archived_feed = anyio.run(
        performance_service.list_feed,
        cast(AsyncSession, object()),
        UUID(int=1),
        None,
        True,
        True,
    )
    assert len(archived_feed) == 2
    assert {item.item_type for item in archived_feed} == {"announcement", "poll"}

    restored_poll = anyio.run(
        performance_service.unarchive_poll,
        cast(AsyncSession, object()),
        poll.id,
    )
    assert restored_poll.status == "closed"


def test_poll_single_choice_vote_replaces_previous(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "PollRepository", FakePollRepository)

    poll = anyio.run(
        performance_service.create_poll,
        cast(AsyncSession, object()),
        UUID(int=1),
        PollCreateRequest(
            question="Where should we host the team event?",
            choices=[
                PollChoiceCreateRequest(text="Cafe"),
                PollChoiceCreateRequest(text="Office"),
            ],
        ),
    )
    assert len(poll.choices) == 2

    published = anyio.run(
        performance_service.publish_poll,
        cast(AsyncSession, object()),
        poll.id,
    )
    assert published.status == "published"

    first_choice = published.choices[0].id
    second_choice = published.choices[1].id

    voted = anyio.run(
        performance_service.submit_poll_vote,
        cast(AsyncSession, object()),
        poll.id,
        UUID(int=2),
        PollVoteSubmitRequest(choice_ids=[first_choice]),
    )
    assert voted.user_vote_choice_ids == [first_choice]

    voted_again = anyio.run(
        performance_service.submit_poll_vote,
        cast(AsyncSession, object()),
        poll.id,
        UUID(int=2),
        PollVoteSubmitRequest(choice_ids=[second_choice]),
    )
    assert voted_again.user_vote_choice_ids == [second_choice]
    counts = {choice.id: choice.vote_count for choice in voted_again.choices}
    assert counts[first_choice] == 0
    assert counts[second_choice] == 1

    try:
        anyio.run(
            performance_service.submit_poll_vote,
            cast(AsyncSession, object()),
            poll.id,
            UUID(int=2),
            PollVoteSubmitRequest(choice_ids=[first_choice, second_choice]),
        )
        assert False, "Expected a ConflictError"
    except ConflictError:
        assert True


def test_shared_resource_confidential_visibility(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "SharedResourceRepository", FakeSharedResourceRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    created = anyio.run(
        performance_service.create_shared_resource,
        cast(AsyncSession, object()),
        UUID(int=1),
        SharedResourceCreateRequest(
            resource_name="HR policy",
            description="policy link",
            storage_key="1/policy.pdf",
            original_filename="policy.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            shared_user_ids=[UUID(int=2)],
            is_confidential=True,
            confidential_access_user_ids=[UUID(int=2)],
        ),
    )
    assert created.shared_user_ids == [UUID(int=2)]
    assert created.confidential_access_user_ids == [UUID(int=2)]

    visible_to_peer = anyio.run(
        performance_service.list_shared_resources,
        cast(AsyncSession, object()),
        UUID(int=2),
        None,
        None,
    )
    assert len(visible_to_peer) == 1

    anyio.run(
        performance_service.remove_shared_resource_confidential_access,
        cast(AsyncSession, object()),
        created.id,
        UUID(int=2),
        UUID(int=1),
        False,
    )
    hidden_from_peer = anyio.run(
        performance_service.list_shared_resources,
        cast(AsyncSession, object()),
        UUID(int=2),
        None,
        None,
    )
    assert hidden_from_peer == []


def test_shared_resource_confidential_requires_shared_user(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "SharedResourceRepository", FakeSharedResourceRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    try:
        anyio.run(
            performance_service.create_shared_resource,
            cast(AsyncSession, object()),
            UUID(int=1),
            SharedResourceCreateRequest(
                resource_name="Compensation sheet",
                storage_key="1/comp-sheet.xlsx",
                original_filename="comp-sheet.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes=4096,
                is_confidential=True,
                confidential_access_user_ids=[UUID(int=2)],
            ),
        )
        assert False, "Expected a ConflictError"
    except ConflictError:
        assert True


def test_shared_resource_update_denied_for_non_owner(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "SharedResourceRepository", FakeSharedResourceRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    created = anyio.run(
        performance_service.create_shared_resource,
        cast(AsyncSession, object()),
        UUID(int=1),
        SharedResourceCreateRequest(
            resource_name="Onboarding",
            storage_key="1/onboarding.docx",
            original_filename="onboarding.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=2048,
            shared_user_ids=[UUID(int=2)],
        ),
    )

    try:
        anyio.run(
            performance_service.update_shared_resource,
            cast(AsyncSession, object()),
            created.id,
            SharedResourceUpdateRequest(resource_name="Renamed"),
            UUID(int=2),
            False,
        )
        assert False, "Expected a PermissionDeniedError"
    except PermissionDeniedError:
        assert True


def test_replace_shared_resource_access_updates_all_users(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "SharedResourceRepository", FakeSharedResourceRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)
    FakeUserRepository.users[UUID(int=3)] = User(
        id=UUID(int=3),
        email="third@example.com",
        password_hash="hashed",
        first_name="Third",
        last_name="Three",
        department_id=1,
        is_active=True,
        is_superuser=False,
        can_modify_shift=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    created = anyio.run(
        performance_service.create_shared_resource,
        cast(AsyncSession, object()),
        UUID(int=1),
        SharedResourceCreateRequest(
            resource_name="Operations Memo",
            storage_key="1/ops-memo.pdf",
            original_filename="ops-memo.pdf",
            content_type="application/pdf",
            size_bytes=2048,
            shared_user_ids=[UUID(int=2)],
            is_confidential=True,
            confidential_access_user_ids=[UUID(int=2)],
        ),
    )

    updated = anyio.run(
        performance_service.replace_shared_resource_access,
        cast(AsyncSession, object()),
        created.id,
        SharedResourceAccessReplaceRequest(
            shared_user_ids=[UUID(int=3), UUID(int=2)],
            confidential_access_user_ids=[UUID(int=3)],
        ),
        UUID(int=1),
        False,
    )

    assert set(updated.shared_user_ids) == {UUID(int=2), UUID(int=3)}
    assert updated.confidential_access_user_ids == [UUID(int=3)]


def test_replace_shared_resource_access_requires_confidential_subset(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "SharedResourceRepository", FakeSharedResourceRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)
    FakeUserRepository.users[UUID(int=3)] = User(
        id=UUID(int=3),
        email="third@example.com",
        password_hash="hashed",
        first_name="Third",
        last_name="Three",
        department_id=1,
        is_active=True,
        is_superuser=False,
        can_modify_shift=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    created = anyio.run(
        performance_service.create_shared_resource,
        cast(AsyncSession, object()),
        UUID(int=1),
        SharedResourceCreateRequest(
            resource_name="Memo",
            storage_key="1/memo.pdf",
            original_filename="memo.pdf",
            content_type="application/pdf",
            size_bytes=512,
            is_confidential=True,
        ),
    )

    try:
        anyio.run(
            performance_service.replace_shared_resource_access,
            cast(AsyncSession, object()),
            created.id,
            SharedResourceAccessReplaceRequest(
                shared_user_ids=[UUID(int=2)],
                confidential_access_user_ids=[UUID(int=3)],
            ),
            UUID(int=1),
            False,
        )
        assert False, "Expected a ConflictError"
    except ConflictError:
        assert True


def test_finalize_requires_peer_assignment(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="PE-REQ",
            title="Performance Evaluation",
            content={"questionnaire_content": [{"domain_number": "1", "questions": []}]},
        ),
    )
    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )

    try:
        anyio.run(
            performance_service.toggle_user_evaluation_finalized,
            cast(AsyncSession, object()),
            user_evaluation.id,
        )
        assert False, "Expected a ConflictError"
    except ConflictError:
        assert True


def test_submit_requires_complete_peer_feedback(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="PE-PEER",
            title="Performance Evaluation",
            content={
                "questionnaire_content": [
                    {"domain_number": "1", "questions": [{"indicator_number": "1", "rating": None}]}
                ]
            },
        ),
    )
    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    anyio.run(
        performance_service.assign_user_evaluation_evaluator,
        cast(AsyncSession, object()),
        user_evaluation.id,
        EvaluationAssignmentRequest(evaluator_id=UUID(int=2)),
    )
    anyio.run(
        performance_service.toggle_user_evaluation_finalized,
        cast(AsyncSession, object()),
        user_evaluation.id,
    )
    peer_evaluation = anyio.run(
        performance_service.create_evaluation,
        cast(AsyncSession, object()),
        user_evaluation.id,
        UUID(int=2),
        EvaluationCreateRequest(
            content_data=[
                {
                    "domain_number": "1",
                    "questions": [{"indicator_number": "1", "rating": 4}],
                }
            ],
        ),
    )

    try:
        anyio.run(
            performance_service.submit_evaluation,
            cast(AsyncSession, object()),
            peer_evaluation.id,
            UUID(int=2),
        )
        assert False, "Expected a ConflictError"
    except ConflictError:
        assert True


def test_update_evaluation_denied_for_non_owner(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="PE-OWN",
            title="Performance Evaluation",
            content={"questionnaire_content": [{"domain_number": "1", "questions": []}]},
        ),
    )
    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    anyio.run(
        performance_service.assign_user_evaluation_evaluator,
        cast(AsyncSession, object()),
        user_evaluation.id,
        EvaluationAssignmentRequest(evaluator_id=UUID(int=2)),
    )
    anyio.run(
        performance_service.toggle_user_evaluation_finalized,
        cast(AsyncSession, object()),
        user_evaluation.id,
    )
    created = anyio.run(
        performance_service.create_evaluation,
        cast(AsyncSession, object()),
        user_evaluation.id,
        UUID(int=2),
        EvaluationCreateRequest(),
    )

    try:
        anyio.run(
            performance_service.update_evaluation,
            cast(AsyncSession, object()),
            created.id,
            EvaluationUpdateRequest(positive_feedback="x"),
            UUID(int=1),
        )
        assert False, "Expected a PermissionDeniedError"
    except PermissionDeniedError:
        assert True


def test_staff_can_rate_only_assigned_evaluations(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    hr_user = User(
        id=UUID(int=3),
        email="hr@example.com",
        password_hash="hashed",
        first_name="HR",
        last_name="Evaluator",
        department_id=1,
        role="HR",
        is_active=True,
        is_superuser=False,
        can_modify_shift=False,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    hr_user.department = FakeUserRepository.users[UUID(int=1)].department
    FakeUserRepository.users[UUID(int=3)] = hr_user

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="PE-HR",
            title="Performance Evaluation",
            content={
                "questionnaire_content": [
                    {
                        "domain_number": "1",
                        "questions": [{"indicator_number": "1", "rating": None}],
                    }
                ]
            },
        ),
    )
    session = cast(AsyncSession, object())
    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        session,
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    self_evaluation = next(
        item
        for item in FakeEvaluationRepository.items.values()
        if item.evaluator_id == UUID(int=1)
    )

    with pytest.raises(PermissionDeniedError):
        anyio.run(
            performance_service.create_evaluation,
            session,
            user_evaluation.id,
            UUID(int=3),
            EvaluationCreateRequest(),
            True,
        )

    assigned_evaluation = anyio.run(
        performance_service.assign_user_evaluation_evaluator,
        session,
        user_evaluation.id,
        EvaluationAssignmentRequest(evaluator_id=UUID(int=3)),
    )
    anyio.run(
        performance_service.toggle_user_evaluation_finalized,
        session,
        user_evaluation.id,
    )
    assert assigned_evaluation.evaluator_id == UUID(int=3)
    assert self_evaluation.evaluator_id == UUID(int=1)
    assert assigned_evaluation.id != self_evaluation.id

    async def list_assigned_cycles():
        return await performance_service.list_user_evaluations(
            session,
            is_finalized=True,
            current_user_id=UUID(int=3),
            is_staff=True,
            evaluator_id=UUID(int=3),
            is_submitted=False,
        )

    assigned_cycles = anyio.run(list_assigned_cycles)
    assert [cycle.id for cycle in assigned_cycles] == [user_evaluation.id]

    with pytest.raises(PermissionDeniedError):
        anyio.run(
            performance_service.update_evaluation,
            session,
            self_evaluation.id,
            EvaluationUpdateRequest(positive_feedback="Not assigned"),
            UUID(int=3),
        )
    with pytest.raises(PermissionDeniedError):
        anyio.run(
            performance_service.submit_evaluation,
            session,
            self_evaluation.id,
            UUID(int=3),
        )

    updated = anyio.run(
        performance_service.update_evaluation,
        session,
        assigned_evaluation.id,
        EvaluationUpdateRequest(
            content_data=[
                {
                    "domain_number": "1",
                    "questions": [{"indicator_number": "1", "rating": 5}],
                }
            ],
            positive_feedback="Strong collaboration.",
            improvement_suggestion="Keep sharing context early.",
        ),
        UUID(int=3),
    )
    assert updated.content_data[0]["questions"][0]["rating"] == 5

    submitted = anyio.run(
        performance_service.submit_evaluation,
        session,
        assigned_evaluation.id,
        UUID(int=3),
    )
    assert submitted.date_submitted is not None


def test_non_staff_cannot_create_unassigned_evaluation(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="PE-SEC",
            title="Performance Evaluation",
            content={"questionnaire_content": [{"domain_number": "1", "questions": []}]},
        ),
    )
    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    try:
        anyio.run(
            performance_service.create_evaluation,
            cast(AsyncSession, object()),
            user_evaluation.id,
            UUID(int=2),
            EvaluationCreateRequest(),
            False,
        )
        assert False, "Expected a PermissionDeniedError"
    except PermissionDeniedError:
        assert True


def test_aggregate_summary_requires_self_submission_for_evaluatee(monkeypatch):
    _reset()
    _seed()
    monkeypatch.setattr(performance_service, "QuestionnaireRepository", FakeQuestionnaireRepository)
    monkeypatch.setattr(performance_service, "UserEvaluationRepository", FakeUserEvaluationRepository)
    monkeypatch.setattr(performance_service, "EvaluationRepository", FakeEvaluationRepository)
    monkeypatch.setattr(performance_service, "UserRepository", FakeUserRepository)

    questionnaire = anyio.run(
        performance_service.create_questionnaire,
        cast(AsyncSession, object()),
        QuestionnaireCreateRequest(
            code="PE-SUM",
            title="Performance Evaluation",
            content={
                "questionnaire_content": [
                    {"domain_number": "1", "questions": [{"indicator_number": "1", "rating": None}]}
                ]
            },
        ),
    )
    user_evaluation = anyio.run(
        performance_service.create_user_evaluation,
        cast(AsyncSession, object()),
        UserEvaluationCreateRequest(
            evaluatee_id=UUID(int=1),
            questionnaire_id=questionnaire.id,
            quarter="FQ",
            year=2026,
        ),
    )
    anyio.run(
        performance_service.assign_user_evaluation_evaluator,
        cast(AsyncSession, object()),
        user_evaluation.id,
        EvaluationAssignmentRequest(evaluator_id=UUID(int=2)),
    )
    anyio.run(
        performance_service.toggle_user_evaluation_finalized,
        cast(AsyncSession, object()),
        user_evaluation.id,
    )

    try:
        anyio.run(
            performance_service.get_user_evaluation_aggregate_summary,
            cast(AsyncSession, object()),
            user_evaluation.id,
            UUID(int=1),
            False,
        )
        assert False, "Expected a PermissionDeniedError"
    except PermissionDeniedError:
        assert True
