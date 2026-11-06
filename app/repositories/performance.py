from __future__ import annotations

from typing import List
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


class QuestionnaireRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, include_inactive: bool = False) -> List[Questionnaire]:
        statement = select(Questionnaire).order_by(Questionnaire.title)
        if not include_inactive:
            statement = statement.where(Questionnaire.is_active.is_(True))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_id(self, questionnaire_id: int) -> Questionnaire | None:
        result = await self.session.execute(
            select(Questionnaire).where(Questionnaire.id == questionnaire_id)
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Questionnaire | None:
        result = await self.session.execute(
            select(Questionnaire).where(Questionnaire.code == code.upper())
        )
        return result.scalar_one_or_none()

    async def create(self, questionnaire: Questionnaire) -> Questionnaire:
        self.session.add(questionnaire)
        await self.session.commit()
        await self.session.refresh(questionnaire)
        return questionnaire

    async def save(self, questionnaire: Questionnaire) -> Questionnaire:
        await self.session.commit()
        await self.session.refresh(questionnaire)
        return questionnaire

    async def delete(self, questionnaire: Questionnaire) -> None:
        await self.session.delete(questionnaire)
        await self.session.commit()


class UserEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        evaluatee_id: UUID | None = None,
        questionnaire_id: int | None = None,
        quarter: str | None = None,
        year: int | None = None,
        is_finalized: bool | None = None,
        evaluator_id: UUID | None = None,
        is_submitted: bool | None = None,
    ) -> List[UserEvaluation]:
        statement = (
            select(UserEvaluation)
            .options(
                selectinload(UserEvaluation.evaluatee).selectinload(User.department),
                selectinload(UserEvaluation.questionnaire),
                selectinload(UserEvaluation.evaluations),
            )
            .order_by(UserEvaluation.year.desc(), UserEvaluation.quarter.desc())
        )
        if evaluatee_id is not None:
            statement = statement.where(UserEvaluation.evaluatee_id == evaluatee_id)
        if questionnaire_id is not None:
            statement = statement.where(UserEvaluation.questionnaire_id == questionnaire_id)
        if quarter is not None:
            statement = statement.where(UserEvaluation.quarter == quarter)
        if year is not None:
            statement = statement.where(UserEvaluation.year == year)
        if is_finalized is not None:
            statement = statement.where(UserEvaluation.is_finalized.is_(is_finalized))
        evaluation_filters = []
        if evaluator_id is not None:
            evaluation_filters.append(Evaluation.evaluator_id == evaluator_id)
        if is_submitted is not None:
            evaluation_filters.append(
                Evaluation.date_submitted.is_not(None)
                if is_submitted
                else Evaluation.date_submitted.is_(None)
            )
        if evaluation_filters:
            statement = statement.where(
                UserEvaluation.evaluations.any(and_(*evaluation_filters))
            )
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def get_by_id(self, user_evaluation_id: int) -> UserEvaluation | None:
        result = await self.session.execute(
            select(UserEvaluation)
            .options(
                selectinload(UserEvaluation.evaluatee).selectinload(User.department),
                selectinload(UserEvaluation.questionnaire),
                selectinload(UserEvaluation.evaluations)
                .selectinload(Evaluation.evaluator)
                .selectinload(User.department),
                selectinload(UserEvaluation.evaluations).selectinload(Evaluation.questionnaire),
            )
            .where(UserEvaluation.id == user_evaluation_id)
        )
        return result.scalar_one_or_none()

    async def get_by_identity(
        self,
        evaluatee_id: UUID,
        questionnaire_id: int,
        quarter: str,
        year: int,
    ) -> UserEvaluation | None:
        result = await self.session.execute(
            select(UserEvaluation).where(
                UserEvaluation.evaluatee_id == evaluatee_id,
                UserEvaluation.questionnaire_id == questionnaire_id,
                UserEvaluation.quarter == quarter,
                UserEvaluation.year == year,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, item: UserEvaluation) -> UserEvaluation:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def save(self, item: UserEvaluation) -> UserEvaluation:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: UserEvaluation) -> None:
        await self.session.delete(item)
        await self.session.commit()


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        user_evaluation_id: int | None = None,
        evaluator_id: UUID | None = None,
        is_submitted: bool | None = None,
    ) -> List[Evaluation]:
        statement = (
            select(Evaluation)
            .options(
                selectinload(Evaluation.evaluator).selectinload(User.department),
                selectinload(Evaluation.user_evaluation)
                .selectinload(UserEvaluation.evaluatee)
                .selectinload(User.department),
                selectinload(Evaluation.user_evaluation).selectinload(UserEvaluation.questionnaire),
                selectinload(Evaluation.questionnaire),
            )
            .order_by(Evaluation.created_at.desc())
        )
        if user_evaluation_id is not None:
            statement = statement.where(Evaluation.user_evaluation_id == user_evaluation_id)
        if evaluator_id is not None:
            statement = statement.where(Evaluation.evaluator_id == evaluator_id)
        if is_submitted is not None:
            if is_submitted:
                statement = statement.where(Evaluation.date_submitted.is_not(None))
            else:
                statement = statement.where(Evaluation.date_submitted.is_(None))
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def get_by_id(self, evaluation_id: int) -> Evaluation | None:
        result = await self.session.execute(
            select(Evaluation)
            .options(
                selectinload(Evaluation.evaluator).selectinload(User.department),
                selectinload(Evaluation.user_evaluation)
                .selectinload(UserEvaluation.evaluatee)
                .selectinload(User.department),
                selectinload(Evaluation.user_evaluation).selectinload(UserEvaluation.questionnaire),
                selectinload(Evaluation.questionnaire),
            )
            .where(Evaluation.id == evaluation_id)
        )
        return result.scalar_one_or_none()

    async def get_by_identity(self, user_evaluation_id: int, evaluator_id: UUID) -> Evaluation | None:
        result = await self.session.execute(
            select(Evaluation).where(
                Evaluation.user_evaluation_id == user_evaluation_id,
                Evaluation.evaluator_id == evaluator_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None
        return await self.get_by_id(item.id)

    async def create(self, item: Evaluation) -> Evaluation:
        self.session.add(item)
        await self.session.commit()
        return await self.get_by_id(item.id)  # type: ignore[return-value]

    async def save(self, item: Evaluation) -> Evaluation:
        await self.session.commit()
        return await self.get_by_id(item.id)  # type: ignore[return-value]

    async def delete(self, item: Evaluation) -> None:
        await self.session.delete(item)
        await self.session.commit()


class SharedResourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(
        self,
        user_id: UUID,
        uploader_id: UUID | None = None,
        search: str | None = None,
    ) -> List[SharedResource]:
        statement = (
            select(SharedResource)
            .options(
                selectinload(SharedResource.uploader),
                selectinload(SharedResource.shares),
                selectinload(SharedResource.confidential_access),
            )
            .join(
                SharedResourceShare,
                SharedResourceShare.resource_id == SharedResource.id,
                isouter=True,
            )
            .where(
                or_(
                    SharedResource.uploader_id == user_id,
                    SharedResourceShare.user_id == user_id,
                )
            )
            .order_by(SharedResource.created_at.desc())
        )
        if uploader_id is not None:
            statement = statement.where(SharedResource.uploader_id == uploader_id)
        if search:
            statement = statement.where(SharedResource.resource_name.ilike(f"%{search}%"))

        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def get_by_id(self, resource_id: int) -> SharedResource | None:
        result = await self.session.execute(
            select(SharedResource)
            .options(
                selectinload(SharedResource.uploader),
                selectinload(SharedResource.shares),
                selectinload(SharedResource.confidential_access),
            )
            .where(SharedResource.id == resource_id)
        )
        return result.scalar_one_or_none()

    async def create(self, item: SharedResource) -> SharedResource:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def save(self, item: SharedResource) -> SharedResource:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: SharedResource) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def get_share(
        self,
        resource_id: int,
        user_id: UUID,
    ) -> SharedResourceShare | None:
        result = await self.session.execute(
            select(SharedResourceShare).where(
                SharedResourceShare.resource_id == resource_id,
                SharedResourceShare.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_share(
        self,
        resource_id: int,
        user_id: UUID,
    ) -> SharedResourceShare:
        item = SharedResourceShare(resource_id=resource_id, user_id=user_id)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def remove_share(self, item: SharedResourceShare) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def get_confidential_access(
        self,
        resource_id: int,
        user_id: UUID,
    ) -> SharedResourceConfidentialAccess | None:
        result = await self.session.execute(
            select(SharedResourceConfidentialAccess).where(
                SharedResourceConfidentialAccess.resource_id == resource_id,
                SharedResourceConfidentialAccess.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_confidential_access(
        self,
        resource_id: int,
        user_id: UUID,
    ) -> SharedResourceConfidentialAccess:
        item = SharedResourceConfidentialAccess(resource_id=resource_id, user_id=user_id)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def remove_confidential_access(self, item: SharedResourceConfidentialAccess) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def clear_confidential_access(self, resource_id: int) -> None:
        result = await self.session.execute(
            select(SharedResourceConfidentialAccess).where(
                SharedResourceConfidentialAccess.resource_id == resource_id
            )
        )
        items = list(result.scalars().all())
        for item in items:
            await self.session.delete(item)
        await self.session.commit()


class AnnouncementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, statuses: List[str] | None = None) -> List[Announcement]:
        statement = select(Announcement).order_by(Announcement.created_at.desc())
        if statuses:
            statement = statement.where(Announcement.status.in_(statuses))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_id(self, announcement_id: int) -> Announcement | None:
        result = await self.session.execute(
            select(Announcement).where(Announcement.id == announcement_id)
        )
        return result.scalar_one_or_none()

    async def create(self, item: Announcement) -> Announcement:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def save(self, item: Announcement) -> Announcement:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: Announcement) -> None:
        await self.session.delete(item)
        await self.session.commit()


class PollRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, statuses: List[str] | None = None) -> List[Poll]:
        statement = (
            select(Poll)
            .options(
                selectinload(Poll.choices),
                selectinload(Poll.votes),
            )
            .order_by(Poll.created_at.desc())
        )
        if statuses:
            statement = statement.where(Poll.status.in_(statuses))
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def get_by_id(self, poll_id: int) -> Poll | None:
        result = await self.session.execute(
            select(Poll)
            .options(
                selectinload(Poll.choices),
                selectinload(Poll.votes),
            )
            .where(Poll.id == poll_id)
        )
        return result.scalar_one_or_none()

    async def create(self, item: Poll) -> Poll:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return await self.get_by_id(item.id)  # type: ignore[return-value]

    async def save(self, item: Poll) -> Poll:
        await self.session.commit()
        await self.session.refresh(item)
        return await self.get_by_id(item.id)  # type: ignore[return-value]

    async def delete(self, item: Poll) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def add_choice(self, item: PollChoice) -> PollChoice:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete_choice(self, item: PollChoice) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def list_votes_for_user(self, poll_id: int, user_id: UUID) -> List[PollVote]:
        result = await self.session.execute(
            select(PollVote).where(PollVote.poll_id == poll_id, PollVote.user_id == user_id)
        )
        return list(result.scalars().all())

    async def add_vote(self, item: PollVote) -> PollVote:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete_vote(self, item: PollVote) -> None:
        await self.session.delete(item)
        await self.session.commit()
