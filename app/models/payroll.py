from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.models.base import Base

position_departments = Table(
    "position_departments",
    Base.metadata,
    Column("position_id", ForeignKey("positions.id"), primary_key=True),
    Column("department_id", ForeignKey("departments.id"), primary_key=True),
)

fixed_compensation_users = Table(
    "fixed_compensation_users",
    Base.metadata,
    Column("fixed_compensation_id", ForeignKey("fixed_compensations.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class PayrollSetting(Base):
    __tablename__ = "payroll_settings"
    __table_args__ = (
        CheckConstraint(
            "automatic_deduction_schedule IN ('SECOND_CUTOFF_ONLY', 'SPLIT_BOTH_CUTOFFS')",
            name="ck_payroll_settings_automatic_deduction_schedule",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deduction_config: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    automatic_deduction_schedule: Mapped[str] = mapped_column(
        String(32), default="SECOND_CUTOFF_ONLY", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

class Mp2Enrollment(Base):
    __tablename__ = "mp2_enrollments"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'ended')", name="ck_mp2_enrollments_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    mp2_account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("code", name="jobs_code_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    departments = relationship("Department", secondary=position_departments)


class FixedCompensation(Base):
    __tablename__ = "fixed_compensations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    users = relationship("User", secondary=fixed_compensation_users)


class Payslip(Base):
    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "month",
            "year",
            "period",
            name="uq_payslips_identity",
        ),
        CheckConstraint(
            "automatic_deduction_schedule IS NULL OR automatic_deduction_schedule IN "
            "('SECOND_CUTOFF_ONLY', 'SPLIT_BOTH_CUTOFFS')",
            name="ck_payslips_automatic_deduction_schedule",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    automatic_deduction_schedule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period: Mapped[str | None] = mapped_column(String(3), nullable=True)
    released: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    release_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="payslips")
    variable_compensations = relationship(
        "PayslipVariableCompensation", back_populates="payslip", cascade="all, delete-orphan"
    )
    variable_deductions = relationship(
        "PayslipVariableDeduction", back_populates="payslip", cascade="all, delete-orphan"
    )


class PayslipVariableCompensation(Base):
    __tablename__ = "payslip_variable_compensations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payslip_id: Mapped[int] = mapped_column(ForeignKey("payslips.id"), index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    payslip = relationship("Payslip", back_populates="variable_compensations")


class PayslipVariableDeduction(Base):
    __tablename__ = "payslip_variable_deductions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payslip_id: Mapped[int] = mapped_column(ForeignKey("payslips.id"), index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    payslip = relationship("Payslip", back_populates="variable_deductions")


class ThirteenthMonthPayout(Base):
    __tablename__ = "thirteenth_month_payouts"
    __table_args__ = (
        UniqueConstraint("user_id", "year", name="uq_thirteenth_month_payout_user_year"),
        CheckConstraint(
            "status IN ('DRAFT', 'RELEASED')",
            name="ck_thirteenth_month_payouts_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    year: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    total_deductions: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="thirteenth_month_payouts")
    adjustments = relationship(
        "ThirteenthMonthAdjustment",
        back_populates="payout",
        cascade="all, delete-orphan",
    )


class ThirteenthMonthAdjustment(Base):
    __tablename__ = "thirteenth_month_adjustments"
    __table_args__ = (
        CheckConstraint(
            "type IN ('ADD', 'DEDUCT')",
            name="ck_thirteenth_month_adjustments_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payout_id: Mapped[int] = mapped_column(
        ForeignKey("thirteenth_month_payouts.id"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    payout = relationship("ThirteenthMonthPayout", back_populates="adjustments")


class PayrollPolicyVersion(Base):
    __tablename__ = "payroll_policy_versions"
    __table_args__ = (
        UniqueConstraint("policy_key", "version_label", name="uq_policy_key_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_key: Mapped[str] = mapped_column(String(100), nullable=False)
    version_label: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PolicySssBracket(Base):
    __tablename__ = "policy_sss_brackets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_version_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_policy_versions.id"), nullable=False, index=True
    )
    legacy_min_compensation: Mapped[Decimal] = mapped_column(
        "min_compensation", Numeric(12, 2), nullable=False
    )
    legacy_max_compensation: Mapped[Decimal] = mapped_column(
        "max_compensation", Numeric(12, 2), nullable=False
    )
    legacy_employee_share: Mapped[Decimal] = mapped_column(
        "employee_share", Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    legacy_employer_share: Mapped[Decimal] = mapped_column(
        "employer_share", Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    compensation_range_from: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    compensation_range_to: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    monthly_salary_credit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    employee_contribution: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    employer_contribution: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    ec_contribution: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    mpf_employee_contribution: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    mpf_employer_contribution: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PolicyPhilhealthRule(Base):
    __tablename__ = "policy_philhealth_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_version_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_policy_versions.id"), nullable=False, index=True
    )
    legacy_min_compensation: Mapped[Decimal] = mapped_column(
        "min_compensation", Numeric(12, 2), nullable=False
    )
    legacy_max_compensation: Mapped[Decimal] = mapped_column(
        "max_compensation", Numeric(12, 2), nullable=False
    )
    legacy_rate: Mapped[Decimal] = mapped_column("rate", Numeric(8, 6), nullable=False)
    compensation_range_from: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    compensation_range_to: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    premium_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    employee_share_ratio: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0.500000"), nullable=False
    )
    employer_share_ratio: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0.500000"), nullable=False
    )
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PolicyPagibigRule(Base):
    __tablename__ = "policy_pagibig_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_version_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_policy_versions.id"), nullable=False, index=True
    )
    legacy_min_compensation: Mapped[Decimal] = mapped_column(
        "min_compensation", Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    legacy_monthly_compensation_cap: Mapped[Decimal] = mapped_column(
        "monthly_compensation_cap", Numeric(12, 2), nullable=False
    )
    legacy_max_employee_share: Mapped[Decimal | None] = mapped_column(
        "max_employee_share", Numeric(12, 2), nullable=True
    )
    legacy_max_employer_share: Mapped[Decimal | None] = mapped_column(
        "max_employer_share", Numeric(12, 2), nullable=True
    )
    compensation_range_from: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    compensation_range_to: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    compensation_cap: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    employee_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    employer_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    employee_share_cap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    employer_share_cap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PolicyBirWithholdingBracket(Base):
    __tablename__ = "policy_bir_withholding_brackets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_version_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_policy_versions.id"), nullable=False, index=True
    )
    payroll_period: Mapped[str] = mapped_column(String(20), nullable=False)
    legacy_min_compensation: Mapped[Decimal] = mapped_column(
        "min_compensation", Numeric(12, 2), nullable=False
    )
    legacy_max_compensation: Mapped[Decimal | None] = mapped_column(
        "max_compensation", Numeric(12, 2), nullable=True
    )
    compensation_range_from: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    compensation_range_to: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    base_tax: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    marginal_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    legacy_over_amount: Mapped[Decimal] = mapped_column(
        "over_amount", Numeric(12, 2), nullable=False
    )
    excess_over: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PolicyMinimumWageOrder(Base):
    __tablename__ = "policy_min_wage_orders"
    __table_args__ = (
        UniqueConstraint(
            "policy_version_id",
            "region_code",
            "sector",
            "effective_from",
            name="uq_min_wage_policy_region_sector_effective",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_version_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_policy_versions.id"), nullable=False, index=True
    )
    region_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sector: Mapped[str] = mapped_column(String(50), default="GENERAL", nullable=False)
    legacy_daily_wage_amount: Mapped[Decimal] = mapped_column(
        "daily_wage_amount", Numeric(12, 2), nullable=False
    )
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PayrollAdjustment(Base):
    __tablename__ = "payroll_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    payslip_id: Mapped[int | None] = mapped_column(ForeignKey("payslips.id"), nullable=True)
    adjustment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class PayslipEvent(Base):
    __tablename__ = "payslip_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payslip_id: Mapped[int] = mapped_column(ForeignKey("payslips.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PayrollPolicySource(Base):
    __tablename__ = "payroll_policy_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    policy_version_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_policy_versions.id"), nullable=False, index=True
    )
    legacy_source_type: Mapped[str] = mapped_column("source_type", String(50), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    applied_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
