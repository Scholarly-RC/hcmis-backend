from __future__ import annotations

from datetime import date
from typing import Any, List
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.payroll import (
    FixedCompensation,
    Position,
    Mp2Enrollment,
    PayrollPolicyVersion,
    PayrollPolicySource,
    PolicySssBracket,
    PolicyPhilhealthRule,
    PolicyPagibigRule,
    PolicyBirWithholdingBracket,
    PolicyMinimumWageOrder,
    PayrollSetting,
    Payslip,
    PayslipEvent,
    PayslipVariableCompensation,
    PayslipVariableDeduction,
    ThirteenthMonthAdjustment,
    ThirteenthMonthPayout,
)
from app.models.user import User


class PayrollSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_first(self) -> PayrollSetting | None:
        result = await self.session.execute(select(PayrollSetting).limit(1))
        return result.scalar_one_or_none()

    async def create(self, settings: PayrollSetting) -> PayrollSetting:
        self.session.add(settings)
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    async def save(self, settings: PayrollSetting) -> PayrollSetting:
        await self.session.commit()
        await self.session.refresh(settings)
        return settings


class PayrollPolicyVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, policy_key: str | None = None) -> List[PayrollPolicyVersion]:
        statement = select(PayrollPolicyVersion).order_by(
            PayrollPolicyVersion.effective_from.desc(),
            PayrollPolicyVersion.created_at.desc(),
        )
        if policy_key is not None:
            statement = statement.where(PayrollPolicyVersion.policy_key == policy_key)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_id(self, policy_version_id: int) -> PayrollPolicyVersion | None:
        result = await self.session.execute(
            select(PayrollPolicyVersion).where(PayrollPolicyVersion.id == policy_version_id)
        )
        return result.scalar_one_or_none()

    async def get_by_identity(self, policy_key: str, version_label: str) -> PayrollPolicyVersion | None:
        result = await self.session.execute(
            select(PayrollPolicyVersion).where(
                PayrollPolicyVersion.policy_key == policy_key,
                PayrollPolicyVersion.version_label == version_label,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_effective(
        self,
        policy_key: str,
        effective_date: date,
    ) -> PayrollPolicyVersion | None:
        result = await self.session.execute(
            select(PayrollPolicyVersion)
            .where(
                and_(
                    PayrollPolicyVersion.policy_key == policy_key,
                    PayrollPolicyVersion.is_active.is_(True),
                    PayrollPolicyVersion.effective_from <= effective_date,
                    or_(
                        PayrollPolicyVersion.effective_to.is_(None),
                        PayrollPolicyVersion.effective_to >= effective_date,
                    ),
                )
            )
            .order_by(
                PayrollPolicyVersion.effective_from.desc(),
                PayrollPolicyVersion.created_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, item: PayrollPolicyVersion) -> PayrollPolicyVersion:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def save(self, item: PayrollPolicyVersion) -> PayrollPolicyVersion:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: PayrollPolicyVersion) -> None:
        await self.session.delete(item)
        await self.session.commit()


class PayrollPolicySourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, policy_version_id: int) -> List[PayrollPolicySource]:
        result = await self.session.execute(
            select(PayrollPolicySource)
            .where(PayrollPolicySource.policy_version_id == policy_version_id)
            .order_by(
                PayrollPolicySource.effective_from.desc(),
                PayrollPolicySource.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def replace(
        self,
        policy_version_id: int,
        sources: List[dict[str, Any]],
        applied_by,
        applied_at,
    ) -> List[PayrollPolicySource]:
        await self.session.execute(
            delete(PayrollPolicySource).where(
                PayrollPolicySource.policy_version_id == policy_version_id
            )
        )
        items = [
            PayrollPolicySource(
                policy_version_id=policy_version_id,
                legacy_source_type=item["document_type"],
                document_type=item["document_type"],
                reference_code=item["reference_code"],
                title=item["title"],
                source_url=item["source_url"],
                published_at=item.get("published_at"),
                effective_from=item["effective_from"],
                effective_to=item.get("effective_to"),
                applied_by=applied_by,
                applied_at=applied_at,
            )
            for item in sources
        ]
        self.session.add_all(items)
        await self.session.commit()
        for item in items:
            await self.session.refresh(item)
        return items


class PayrollPolicyRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def clear_policy_rules(self, policy_version_id: int) -> None:
        await self.session.execute(
            delete(PolicySssBracket).where(PolicySssBracket.policy_version_id == policy_version_id)
        )
        await self.session.execute(
            delete(PolicyPhilhealthRule).where(
                PolicyPhilhealthRule.policy_version_id == policy_version_id
            )
        )
        await self.session.execute(
            delete(PolicyPagibigRule).where(PolicyPagibigRule.policy_version_id == policy_version_id)
        )
        await self.session.execute(
            delete(PolicyBirWithholdingBracket).where(
                PolicyBirWithholdingBracket.policy_version_id == policy_version_id
            )
        )
        await self.session.execute(
            delete(PolicyMinimumWageOrder).where(
                PolicyMinimumWageOrder.policy_version_id == policy_version_id
            )
        )

    async def seed_ph_baseline(self, policy_version_id: int) -> None:
        self.session.add_all(
            [
                PolicySssBracket(
                    policy_version_id=policy_version_id,
                    compensation_range_from=0,
                    compensation_range_to=999999,
                    monthly_salary_credit=0,
                    employee_contribution=0,
                    employer_contribution=0,
                    ec_contribution=0,
                    mpf_employee_contribution=0,
                    mpf_employer_contribution=0,
                ),
                PolicyPhilhealthRule(
                    policy_version_id=policy_version_id,
                    compensation_range_from=0,
                    compensation_range_to=999999,
                    premium_rate=0,
                    employee_share_ratio=0.5,
                    employer_share_ratio=0.5,
                ),
                PolicyPagibigRule(
                    policy_version_id=policy_version_id,
                    compensation_range_from=0,
                    compensation_range_to=None,
                    compensation_cap=100000,
                    employee_rate=0,
                    employer_rate=0,
                    employee_share_cap=0,
                    employer_share_cap=0,
                ),
                PolicyBirWithholdingBracket(
                    policy_version_id=policy_version_id,
                    payroll_period="SEMI_MONTHLY",
                    compensation_range_from=0,
                    compensation_range_to=None,
                    base_tax=0,
                    marginal_rate=0,
                    excess_over=0,
                ),
                PolicyMinimumWageOrder(
                    policy_version_id=policy_version_id,
                    region_code="NCR",
                    sector="GENERAL",
                    daily_rate=0,
                    effective_from=date(2026, 1, 1),
                    effective_to=None,
                    source_reference="To be calibrated against official wage order.",
                ),
            ]
        )
        await self.session.commit()

    async def get_policy_rules(self, policy_version_id: int) -> dict[str, list[Any]]:
        sss_result = await self.session.execute(
            select(PolicySssBracket)
            .where(PolicySssBracket.policy_version_id == policy_version_id)
            .order_by(PolicySssBracket.compensation_range_from.asc())
        )
        philhealth_result = await self.session.execute(
            select(PolicyPhilhealthRule)
            .where(PolicyPhilhealthRule.policy_version_id == policy_version_id)
            .order_by(PolicyPhilhealthRule.compensation_range_from.asc())
        )
        pagibig_result = await self.session.execute(
            select(PolicyPagibigRule)
            .where(PolicyPagibigRule.policy_version_id == policy_version_id)
            .order_by(PolicyPagibigRule.compensation_range_from.asc())
        )
        bir_result = await self.session.execute(
            select(PolicyBirWithholdingBracket)
            .where(PolicyBirWithholdingBracket.policy_version_id == policy_version_id)
            .order_by(
                PolicyBirWithholdingBracket.payroll_period.asc(),
                PolicyBirWithholdingBracket.compensation_range_from.asc(),
            )
        )
        wage_result = await self.session.execute(
            select(PolicyMinimumWageOrder)
            .where(PolicyMinimumWageOrder.policy_version_id == policy_version_id)
            .order_by(
                PolicyMinimumWageOrder.region_code.asc(),
                PolicyMinimumWageOrder.effective_from.desc(),
            )
        )
        return {
            "sss_brackets": list(sss_result.scalars().all()),
            "philhealth_rules": list(philhealth_result.scalars().all()),
            "pagibig_rules": list(pagibig_result.scalars().all()),
            "bir_withholding_brackets": list(bir_result.scalars().all()),
            "minimum_wage_orders": list(wage_result.scalars().all()),
        }

    async def replace_policy_rules(
        self,
        policy_version_id: int,
        payload: dict[str, list[dict[str, Any]]],
    ) -> None:
        await self.clear_policy_rules(policy_version_id)
        self.session.add_all(
            [
                PolicySssBracket(
                    policy_version_id=policy_version_id,
                    legacy_min_compensation=item["compensation_range_from"],
                    legacy_max_compensation=item["compensation_range_to"],
                    legacy_employee_share=item["employee_contribution"]
                    + item["mpf_employee_contribution"],
                    legacy_employer_share=item["employer_contribution"]
                    + item["mpf_employer_contribution"],
                    **item,
                )
                for item in payload["sss_brackets"]
            ]
            + [
                PolicyPhilhealthRule(
                    policy_version_id=policy_version_id,
                    legacy_min_compensation=item["compensation_range_from"],
                    legacy_max_compensation=item["compensation_range_to"],
                    legacy_rate=item["premium_rate"],
                    **item,
                )
                for item in payload["philhealth_rules"]
            ]
            + [
                PolicyPagibigRule(
                    policy_version_id=policy_version_id,
                    legacy_min_compensation=item["compensation_range_from"],
                    legacy_monthly_compensation_cap=item["compensation_cap"],
                    legacy_max_employee_share=item["employee_share_cap"],
                    legacy_max_employer_share=item["employer_share_cap"],
                    **item,
                )
                for item in payload["pagibig_rules"]
            ]
            + [
                PolicyBirWithholdingBracket(
                    policy_version_id=policy_version_id,
                    legacy_min_compensation=item["compensation_range_from"],
                    legacy_max_compensation=item["compensation_range_to"],
                    legacy_over_amount=item["excess_over"],
                    **item,
                )
                for item in payload["bir_withholding_brackets"]
            ]
            + [
                PolicyMinimumWageOrder(
                    policy_version_id=policy_version_id,
                    legacy_daily_wage_amount=item["daily_rate"],
                    **item,
                )
                for item in payload["minimum_wage_orders"]
            ]
        )
        await self.session.commit()


class Mp2EnrollmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, status: str | None = None) -> List[Mp2Enrollment]:
        statement = (
            select(Mp2Enrollment)
            .options(selectinload(Mp2Enrollment.user))
            .order_by(Mp2Enrollment.effective_from.desc(), Mp2Enrollment.id.desc())
        )
        if status is not None:
            statement = statement.where(Mp2Enrollment.status == status)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_id(self, enrollment_id: int) -> Mp2Enrollment | None:
        result = await self.session.execute(
            select(Mp2Enrollment)
            .options(selectinload(Mp2Enrollment.user))
            .where(Mp2Enrollment.id == enrollment_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_user_on(
        self,
        user_id: UUID,
        effective_date: date,
    ) -> Mp2Enrollment | None:
        result = await self.session.execute(
            select(Mp2Enrollment)
            .options(selectinload(Mp2Enrollment.user))
            .where(
                Mp2Enrollment.user_id == user_id,
                Mp2Enrollment.status == "active",
                Mp2Enrollment.effective_from <= effective_date,
                or_(
                    Mp2Enrollment.effective_to.is_(None),
                    Mp2Enrollment.effective_to >= effective_date,
                ),
            )
            .order_by(Mp2Enrollment.effective_from.desc(), Mp2Enrollment.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(self, enrollment: Mp2Enrollment) -> Mp2Enrollment:
        self.session.add(enrollment)
        await self.session.commit()
        refreshed = await self.get_by_id(enrollment.id)
        if refreshed is None:
            return enrollment
        return refreshed

    async def save(self, enrollment: Mp2Enrollment) -> Mp2Enrollment:
        await self.session.commit()
        refreshed = await self.get_by_id(enrollment.id)
        if refreshed is None:
            return enrollment
        return refreshed


class PositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, department_id: int | None = None) -> List[Position]:
        statement = select(Position).options(selectinload(Position.departments)).order_by(Position.title)
        if department_id is not None:
            statement = statement.join(Position.departments).where(Department.id == department_id)
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def get_by_id(self, position_id: int) -> Position | None:
        result = await self.session.execute(
            select(Position).options(selectinload(Position.departments)).where(Position.id == position_id)
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Position | None:
        result = await self.session.execute(
            select(Position).options(selectinload(Position.departments)).where(func.lower(Position.code) == code.lower())
        )
        return result.scalar_one_or_none()

    async def create(self, position: Position) -> Position:
        self.session.add(position)
        await self.session.commit()
        refreshed = await self.get_by_id(position.id)
        if refreshed is None:
            return position
        return refreshed

    async def save(self, position: Position) -> Position:
        await self.session.commit()
        refreshed = await self.get_by_id(position.id)
        if refreshed is None:
            return position
        return refreshed

    async def delete(self, position: Position) -> None:
        await self.session.delete(position)
        await self.session.commit()


class FixedCompensationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, month: int | None = None, year: int | None = None) -> List[FixedCompensation]:
        statement = select(FixedCompensation).options(
            selectinload(FixedCompensation.users).selectinload(User.department)
        ).order_by(FixedCompensation.year.desc(), FixedCompensation.month.desc(), FixedCompensation.name)
        if month is not None:
            statement = statement.where(FixedCompensation.month == month)
        if year is not None:
            statement = statement.where(FixedCompensation.year == year)
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def get_by_id(self, compensation_id: int) -> FixedCompensation | None:
        result = await self.session.execute(
            select(FixedCompensation)
            .options(selectinload(FixedCompensation.users).selectinload(User.department))
            .where(FixedCompensation.id == compensation_id)
        )
        return result.scalar_one_or_none()

    async def create(self, compensation: FixedCompensation) -> FixedCompensation:
        self.session.add(compensation)
        await self.session.commit()
        await self.session.refresh(compensation)
        return compensation

    async def save(self, compensation: FixedCompensation) -> FixedCompensation:
        await self.session.commit()
        await self.session.refresh(compensation)
        return compensation

    async def delete(self, compensation: FixedCompensation) -> None:
        await self.session.delete(compensation)
        await self.session.commit()


class PayslipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _with_relationships(statement):
        return statement.options(
            selectinload(Payslip.user).selectinload(User.department),
            selectinload(Payslip.variable_compensations),
            selectinload(Payslip.variable_deductions),
        )

    async def list(
        self,
        user_id: UUID | None = None,
        month: int | None = None,
        year: int | None = None,
        period: str | None = None,
        released: bool | None = None,
    ) -> List[Payslip]:
        statement = self._with_relationships(select(Payslip))
        if user_id is not None:
            statement = statement.where(Payslip.user_id == user_id)
        if month is not None:
            statement = statement.where(Payslip.month == month)
        if year is not None:
            statement = statement.where(Payslip.year == year)
        if period is not None:
            statement = statement.where(Payslip.period == period)
        if released is not None:
            statement = statement.where(Payslip.released.is_(released))
        statement = statement.order_by(Payslip.year.desc(), Payslip.month.desc(), Payslip.period.desc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_id(self, payslip_id: int) -> Payslip | None:
        result = await self.session.execute(
            self._with_relationships(select(Payslip)).where(Payslip.id == payslip_id)
        )
        return result.scalar_one_or_none()

    async def get_by_identity(self, user_id: UUID, month: int, year: int, period: str) -> Payslip | None:
        result = await self.session.execute(
            self._with_relationships(select(Payslip)).where(
                Payslip.user_id == user_id,
                Payslip.month == month,
                Payslip.year == year,
                Payslip.period == period,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, payslip: Payslip) -> Payslip:
        self.session.add(payslip)
        await self.session.commit()
        await self.session.refresh(payslip)
        loaded = await self.get_by_id(payslip.id)
        return loaded if loaded is not None else payslip

    async def save(self, payslip: Payslip) -> Payslip:
        await self.session.commit()
        await self.session.refresh(payslip)
        loaded = await self.get_by_id(payslip.id)
        return loaded if loaded is not None else payslip

    async def delete(self, payslip: Payslip) -> None:
        await self.session.execute(
            delete(PayslipEvent).where(PayslipEvent.payslip_id == payslip.id)
        )
        await self.session.delete(payslip)
        await self.session.commit()


class PayslipVariableCompensationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: PayslipVariableCompensation) -> PayslipVariableCompensation:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_by_id(self, item_id: int) -> PayslipVariableCompensation | None:
        result = await self.session.execute(
            select(PayslipVariableCompensation).where(PayslipVariableCompensation.id == item_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, item: PayslipVariableCompensation) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def replace_for_payslip(
        self,
        payslip_id: int,
        items: list[dict[str, Any]],
    ) -> list[PayslipVariableCompensation]:
        await self.session.execute(
            delete(PayslipVariableCompensation).where(
                PayslipVariableCompensation.payslip_id == payslip_id
            )
        )
        created_items = [
            PayslipVariableCompensation(
                payslip_id=payslip_id,
                name=item["name"],
                amount=item["amount"],
            )
            for item in items
        ]
        self.session.add_all(created_items)
        await self.session.commit()
        for item in created_items:
            await self.session.refresh(item)
        return created_items


class PayslipVariableDeductionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: PayslipVariableDeduction) -> PayslipVariableDeduction:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_by_id(self, item_id: int) -> PayslipVariableDeduction | None:
        result = await self.session.execute(
            select(PayslipVariableDeduction).where(PayslipVariableDeduction.id == item_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, item: PayslipVariableDeduction) -> None:
        await self.session.delete(item)
        await self.session.commit()

    async def replace_for_payslip(
        self,
        payslip_id: int,
        items: list[dict[str, Any]],
    ) -> list[PayslipVariableDeduction]:
        await self.session.execute(
            delete(PayslipVariableDeduction).where(
                PayslipVariableDeduction.payslip_id == payslip_id
            )
        )
        created_items = [
            PayslipVariableDeduction(
                payslip_id=payslip_id,
                name=item["name"],
                amount=item["amount"],
                source=item.get("source", "MANUAL"),
                source_date=item.get("source_date"),
                source_type=item.get("source_type"),
            )
            for item in items
        ]
        self.session.add_all(created_items)
        await self.session.commit()
        for item in created_items:
            await self.session.refresh(item)
        return created_items

    async def replace_attendance_for_payslip(
        self,
        payslip_id: int,
        items: list[dict[str, Any]],
    ) -> list[PayslipVariableDeduction]:
        await self.session.execute(
            delete(PayslipVariableDeduction).where(
                PayslipVariableDeduction.payslip_id == payslip_id,
                PayslipVariableDeduction.source == "ATTENDANCE",
            )
        )
        created_items = [
            PayslipVariableDeduction(
                payslip_id=payslip_id,
                name=item["name"],
                amount=item["amount"],
                source="ATTENDANCE",
                source_date=item.get("source_date"),
                source_type=item.get("source_type"),
            )
            for item in items
        ]
        self.session.add_all(created_items)
        await self.session.commit()
        for item in created_items:
            await self.session.refresh(item)
        return created_items


class ThirteenthMonthPayoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        user_id: UUID | None = None,
        year: int | None = None,
        status: str | None = None,
    ) -> List[ThirteenthMonthPayout]:
        statement = select(ThirteenthMonthPayout).options(
            selectinload(ThirteenthMonthPayout.user).selectinload(User.department),
            selectinload(ThirteenthMonthPayout.adjustments),
        )
        if user_id is not None:
            statement = statement.where(ThirteenthMonthPayout.user_id == user_id)
        if year is not None:
            statement = statement.where(ThirteenthMonthPayout.year == year)
        if status is not None:
            statement = statement.where(ThirteenthMonthPayout.status == status)
        statement = statement.order_by(
            ThirteenthMonthPayout.year.desc(),
            ThirteenthMonthPayout.id.desc(),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_id(self, item_id: int) -> ThirteenthMonthPayout | None:
        result = await self.session.execute(
            select(ThirteenthMonthPayout)
            .options(
                selectinload(ThirteenthMonthPayout.user).selectinload(User.department),
                selectinload(ThirteenthMonthPayout.adjustments),
            )
            .where(ThirteenthMonthPayout.id == item_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_year(self, user_id: UUID, year: int) -> ThirteenthMonthPayout | None:
        result = await self.session.execute(
            select(ThirteenthMonthPayout).where(
                ThirteenthMonthPayout.user_id == user_id,
                ThirteenthMonthPayout.year == year,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, item: ThirteenthMonthPayout) -> ThirteenthMonthPayout:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def save(self, item: ThirteenthMonthPayout) -> ThirteenthMonthPayout:
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete(self, item: ThirteenthMonthPayout) -> None:
        await self.session.delete(item)
        await self.session.commit()


class ThirteenthMonthAdjustmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: ThirteenthMonthAdjustment) -> ThirteenthMonthAdjustment:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_by_id(self, item_id: int) -> ThirteenthMonthAdjustment | None:
        result = await self.session.execute(
            select(ThirteenthMonthAdjustment).where(
                ThirteenthMonthAdjustment.id == item_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_payout_id(self, payout_id: int) -> list[ThirteenthMonthAdjustment]:
        result = await self.session.execute(
            select(ThirteenthMonthAdjustment)
            .where(ThirteenthMonthAdjustment.payout_id == payout_id)
            .order_by(ThirteenthMonthAdjustment.id.asc())
        )
        return list(result.scalars().all())

    async def delete(self, item: ThirteenthMonthAdjustment) -> None:
        await self.session.delete(item)
        await self.session.commit()
