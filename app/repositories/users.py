from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.user import (
    User,
    UserEmploymentMovement,
    UserPositionAssignment,
    UserSalaryAssignment,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
                selectinload(User.shift_templates),
            )
            .where(User.id == user_id)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
                selectinload(User.shift_templates),
            )
            .where(User.email == email)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
                selectinload(User.shift_templates),
            )
            .where(User.username == username)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_login_identifier(self, identifier: str) -> User | None:
        normalized_identifier = identifier.strip().lower()
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
                selectinload(User.shift_templates),
            )
            .where(
                or_(
                    func.lower(User.email) == normalized_identifier,
                    func.lower(User.username) == normalized_identifier,
                )
            )
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_auth_user_by_login_identifier(self, identifier: str) -> User | None:
        normalized_identifier = identifier.strip().lower()
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
            )
            .where(
                or_(
                    User.email == normalized_identifier,
                    User.username == normalized_identifier,
                )
            )
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_employee_number(self, employee_number: str) -> User | None:
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
                selectinload(User.shift_templates),
            )
            .where(User.employee_number == employee_number)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_biometric_uid(self, biometric_uid: int) -> User | None:
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
                selectinload(User.shift_templates),
            )
            .where(User.biometric_uid == biometric_uid)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(
        self,
        query: str | None = None,
        department_id: int | None = None,
        active_only: bool | None = None,
        include_superusers: bool = False,
        exclude_hr: bool = False,
        exclude_user_id: UUID | None = None,
    ) -> list[User]:
        statement = (
            select(User)
            .options(
                selectinload(User.department),
                selectinload(User.position),
                selectinload(User.shift_templates),
            )
            .outerjoin(Department, Department.id == User.department_id)
        )
        if not include_superusers:
            statement = statement.where(User.is_superuser.is_(False))
        if exclude_hr:
            hr_label = "HR"
            statement = statement.where(func.upper(func.coalesce(User.role, "")) != hr_label)
        if exclude_user_id is not None:
            statement = statement.where(User.id != exclude_user_id)
        if department_id is not None:
            statement = statement.where(User.department_id == department_id)
        if active_only is True:
            statement = statement.where(User.is_active.is_(True))
        if query:
            lowered = f"%{query.lower()}%"
            statement = statement.where(
                func.lower(User.first_name).like(lowered)
                | func.lower(User.last_name).like(lowered)
                | func.lower(User.email).like(lowered)
                | func.lower(User.username).like(lowered)
                | func.lower(User.employee_number).like(lowered)
            )
        statement = statement.order_by(
            func.lower(func.coalesce(User.last_name, "")),
            func.lower(func.coalesce(User.first_name, "")),
            User.id.asc(),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        refreshed = await self.get_by_id(user.id)
        if refreshed is None:
            return user
        return refreshed

    async def save(self, user: User) -> User:
        await self.session.commit()
        refreshed = await self.get_by_id(user.id)
        if refreshed is None:
            return user
        return refreshed


class UserPositionAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _with_relationships(self, statement):
        return statement.options(
            selectinload(UserPositionAssignment.user),
            selectinload(UserPositionAssignment.position),
        )

    async def list_for_user(self, user_id: UUID) -> list[UserPositionAssignment]:
        statement = self._with_relationships(
            select(UserPositionAssignment).where(UserPositionAssignment.user_id == user_id)
        ).order_by(
            UserPositionAssignment.effective_from.desc(),
            UserPositionAssignment.id.desc(),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_active_for_user_on(
        self,
        user_id: UUID,
        effective_date: date,
    ) -> UserPositionAssignment | None:
        statement = (
            self._with_relationships(select(UserPositionAssignment))
            .where(
                and_(
                    UserPositionAssignment.user_id == user_id,
                    UserPositionAssignment.effective_from <= effective_date,
                    or_(
                        UserPositionAssignment.effective_to.is_(None),
                        UserPositionAssignment.effective_to >= effective_date,
                    ),
                )
            )
            .order_by(
                UserPositionAssignment.effective_from.desc(),
                UserPositionAssignment.id.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_overlapping_assignments(
        self,
        user_id: UUID,
        effective_from: date,
        effective_to: date | None,
        exclude_assignment_id: int | None = None,
    ) -> list[UserPositionAssignment]:
        statement = select(UserPositionAssignment).where(
            UserPositionAssignment.user_id == user_id,
            or_(
                UserPositionAssignment.effective_to.is_(None),
                UserPositionAssignment.effective_to >= effective_from,
            ),
        )
        if effective_to is not None:
            statement = statement.where(UserPositionAssignment.effective_from <= effective_to)
        if exclude_assignment_id is not None:
            statement = statement.where(UserPositionAssignment.id != exclude_assignment_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(self, assignment: UserPositionAssignment) -> UserPositionAssignment:
        self.session.add(assignment)
        await self.session.commit()
        result = await self.session.execute(
            self._with_relationships(select(UserPositionAssignment)).where(
                UserPositionAssignment.id == assignment.id
            )
        )
        return result.scalar_one()

    async def save(self, assignment: UserPositionAssignment) -> UserPositionAssignment:
        await self.session.commit()
        result = await self.session.execute(
            self._with_relationships(select(UserPositionAssignment)).where(
                UserPositionAssignment.id == assignment.id
            )
        )
        return result.scalar_one()


class UserSalaryAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _with_relationships(self, statement):
        return statement.options(selectinload(UserSalaryAssignment.user))

    async def list_for_user(self, user_id: UUID) -> list[UserSalaryAssignment]:
        statement = self._with_relationships(
            select(UserSalaryAssignment).where(UserSalaryAssignment.user_id == user_id)
        ).order_by(
            UserSalaryAssignment.effective_from.desc(),
            UserSalaryAssignment.id.desc(),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_active_for_user_on(
        self,
        user_id: UUID,
        effective_date: date,
    ) -> UserSalaryAssignment | None:
        statement = (
            self._with_relationships(select(UserSalaryAssignment))
            .where(
                and_(
                    UserSalaryAssignment.user_id == user_id,
                    UserSalaryAssignment.effective_from <= effective_date,
                    or_(
                        UserSalaryAssignment.effective_to.is_(None),
                        UserSalaryAssignment.effective_to >= effective_date,
                    ),
                )
            )
            .order_by(
                UserSalaryAssignment.effective_from.desc(),
                UserSalaryAssignment.id.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_overlapping_assignments(
        self,
        user_id: UUID,
        effective_from: date,
        effective_to: date | None,
        exclude_assignment_id: int | None = None,
    ) -> list[UserSalaryAssignment]:
        statement = select(UserSalaryAssignment).where(
            UserSalaryAssignment.user_id == user_id,
            or_(
                UserSalaryAssignment.effective_to.is_(None),
                UserSalaryAssignment.effective_to >= effective_from,
            ),
        )
        if effective_to is not None:
            statement = statement.where(UserSalaryAssignment.effective_from <= effective_to)
        if exclude_assignment_id is not None:
            statement = statement.where(UserSalaryAssignment.id != exclude_assignment_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(self, assignment: UserSalaryAssignment) -> UserSalaryAssignment:
        self.session.add(assignment)
        await self.session.commit()
        result = await self.session.execute(
            self._with_relationships(select(UserSalaryAssignment)).where(
                UserSalaryAssignment.id == assignment.id
            )
        )
        return result.scalar_one()

    async def save(self, assignment: UserSalaryAssignment) -> UserSalaryAssignment:
        await self.session.commit()
        result = await self.session.execute(
            self._with_relationships(select(UserSalaryAssignment)).where(
                UserSalaryAssignment.id == assignment.id
            )
        )
        return result.scalar_one()


class UserEmploymentMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_many(
        self,
        movements: list[UserEmploymentMovement],
    ) -> list[UserEmploymentMovement]:
        if not movements:
            return []
        self.session.add_all(movements)
        await self.session.commit()
        return movements

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int = 100,
    ) -> list[UserEmploymentMovement]:
        statement = (
            select(UserEmploymentMovement)
            .where(UserEmploymentMovement.user_id == user_id)
            .order_by(UserEmploymentMovement.changed_at.desc(), UserEmploymentMovement.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
