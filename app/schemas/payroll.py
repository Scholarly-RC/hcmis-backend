from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from app.schemas.department import DepartmentRead
from app.schemas.user import UserRead


class PayrollSettingRead(BaseModel):
    id: int
    deduction_config: list[dict]
    automatic_deduction_schedule: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayrollPolicyVersionRead(BaseModel):
    id: int
    policy_key: str
    version_label: str
    effective_from: date
    effective_to: date | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayrollPolicyVersionCreateRequest(BaseModel):
    policy_key: str = Field(min_length=1, max_length=100)
    version_label: str = Field(min_length=1, max_length=100)
    effective_from: date
    effective_to: date | None = None
    is_active: bool = True


class PayrollPolicySeedRequest(BaseModel):
    version_label: str = Field(min_length=1, max_length=100)
    effective_from: date
    effective_to: date | None = None
    overwrite_existing: bool = False


class PayrollPolicyOfficialSeedRequest(BaseModel):
    version_label: str = Field(min_length=1, max_length=100)
    effective_from: date
    effective_to: date | None = None
    overwrite_existing: bool = False


class PayrollPolicySourceRead(BaseModel):
    id: int
    document_type: str
    reference_code: str
    title: str
    source_url: str
    published_at: date | None = None
    effective_from: date
    effective_to: date | None = None
    applied_by: UUID | None = None
    applied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayrollPolicySourceWrite(BaseModel):
    document_type: str = Field(min_length=1, max_length=50)
    reference_code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    source_url: str = Field(min_length=1, max_length=500)
    published_at: date | None = None
    effective_from: date
    effective_to: date | None = None


class PayrollPolicySourcesUpdateRequest(BaseModel):
    sources: list[PayrollPolicySourceWrite] = Field(default_factory=list)


class PolicySssBracketRead(BaseModel):
    id: int
    compensation_range_from: Decimal
    compensation_range_to: Decimal
    monthly_salary_credit: Decimal
    employee_contribution: Decimal
    employer_contribution: Decimal
    ec_contribution: Decimal
    mpf_employee_contribution: Decimal
    mpf_employer_contribution: Decimal
    source_reference: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicySssBracketWrite(BaseModel):
    compensation_range_from: Decimal = Field(ge=0)
    compensation_range_to: Decimal = Field(ge=0)
    monthly_salary_credit: Decimal = Field(ge=0)
    employee_contribution: Decimal = Field(ge=0)
    employer_contribution: Decimal = Field(ge=0)
    ec_contribution: Decimal = Field(default=Decimal("0.00"), ge=0)
    mpf_employee_contribution: Decimal = Field(default=Decimal("0.00"), ge=0)
    mpf_employer_contribution: Decimal = Field(default=Decimal("0.00"), ge=0)
    source_reference: str | None = Field(default=None, max_length=255)


class PolicyPhilhealthRuleRead(BaseModel):
    id: int
    compensation_range_from: Decimal
    compensation_range_to: Decimal
    premium_rate: Decimal
    employee_share_ratio: Decimal
    employer_share_ratio: Decimal
    source_reference: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyPhilhealthRuleWrite(BaseModel):
    compensation_range_from: Decimal = Field(ge=0)
    compensation_range_to: Decimal = Field(ge=0)
    premium_rate: Decimal = Field(ge=0)
    employee_share_ratio: Decimal = Field(ge=0)
    employer_share_ratio: Decimal = Field(ge=0)
    source_reference: str | None = Field(default=None, max_length=255)


class PolicyPagibigRuleRead(BaseModel):
    id: int
    compensation_range_from: Decimal
    compensation_range_to: Decimal | None = None
    compensation_cap: Decimal
    employee_rate: Decimal
    employer_rate: Decimal
    employee_share_cap: Decimal | None = None
    employer_share_cap: Decimal | None = None
    source_reference: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyPagibigRuleWrite(BaseModel):
    compensation_range_from: Decimal = Field(ge=0)
    compensation_range_to: Decimal | None = Field(default=None, ge=0)
    compensation_cap: Decimal = Field(ge=0)
    employee_rate: Decimal = Field(ge=0)
    employer_rate: Decimal = Field(ge=0)
    employee_share_cap: Decimal | None = Field(default=None, ge=0)
    employer_share_cap: Decimal | None = Field(default=None, ge=0)
    source_reference: str | None = Field(default=None, max_length=255)


class PolicyBirWithholdingBracketRead(BaseModel):
    id: int
    payroll_period: str
    compensation_range_from: Decimal
    compensation_range_to: Decimal | None = None
    base_tax: Decimal
    marginal_rate: Decimal
    excess_over: Decimal
    source_reference: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyBirWithholdingBracketWrite(BaseModel):
    payroll_period: str = Field(pattern="^(DAILY|WEEKLY|SEMI_MONTHLY|MONTHLY|ANNUAL)$")
    compensation_range_from: Decimal = Field(ge=0)
    compensation_range_to: Decimal | None = Field(default=None, ge=0)
    base_tax: Decimal = Field(ge=0)
    marginal_rate: Decimal = Field(ge=0)
    excess_over: Decimal = Field(ge=0)
    source_reference: str | None = Field(default=None, max_length=255)


class PolicyMinimumWageOrderRead(BaseModel):
    id: int
    region_code: str
    sector: str
    daily_rate: Decimal
    effective_from: date
    effective_to: date | None = None
    source_reference: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyMinimumWageOrderWrite(BaseModel):
    region_code: str = Field(min_length=1, max_length=20)
    sector: str = Field(default="GENERAL", min_length=1, max_length=50)
    daily_rate: Decimal = Field(ge=0)
    effective_from: date
    effective_to: date | None = None
    source_reference: str | None = Field(default=None, max_length=255)


class PayrollPolicyRulesRead(BaseModel):
    sss_brackets: list[PolicySssBracketRead] = Field(default_factory=list)
    philhealth_rules: list[PolicyPhilhealthRuleRead] = Field(default_factory=list)
    pagibig_rules: list[PolicyPagibigRuleRead] = Field(default_factory=list)
    bir_withholding_brackets: list[PolicyBirWithholdingBracketRead] = Field(default_factory=list)
    minimum_wage_orders: list[PolicyMinimumWageOrderRead] = Field(default_factory=list)


class PayrollPolicyRulesUpdateRequest(BaseModel):
    sss_brackets: list[PolicySssBracketWrite] = Field(default_factory=list)
    philhealth_rules: list[PolicyPhilhealthRuleWrite] = Field(default_factory=list)
    pagibig_rules: list[PolicyPagibigRuleWrite] = Field(default_factory=list)
    bir_withholding_brackets: list[PolicyBirWithholdingBracketWrite] = Field(default_factory=list)
    minimum_wage_orders: list[PolicyMinimumWageOrderWrite] = Field(default_factory=list)


class PayrollPolicyDetailRead(BaseModel):
    version: PayrollPolicyVersionRead
    rules: PayrollPolicyRulesRead


class PayrollPolicySourcesDetailRead(BaseModel):
    version: PayrollPolicyVersionRead
    sources: list[PayrollPolicySourceRead] = Field(default_factory=list)


class Mp2EnrollmentRead(BaseModel):
    id: int
    user_id: UUID
    amount: Decimal
    effective_from: date
    effective_to: date | None = None
    status: str
    mp2_account_number: str | None = None
    notes: str | None = None
    user: UserRead | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Mp2EnrollmentCreateRequest(BaseModel):
    user_id: UUID
    amount: Decimal = Field(ge=0)
    effective_from: date
    effective_to: date | None = None
    status: str = Field(default="active", pattern="^(active|ended)$")
    mp2_account_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)


class Mp2EnrollmentUpdateRequest(BaseModel):
    amount: Decimal | None = Field(default=None, ge=0)
    effective_from: date | None = None
    effective_to: date | None = None
    status: str | None = Field(default=None, pattern="^(active|ended)$")
    mp2_account_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)


class PayrollSettingUpdateRequest(BaseModel):
    deduction_config: list[dict] | None = None
    automatic_deduction_schedule: str | None = Field(
        default=None,
        pattern="^(SECOND_CUTOFF_ONLY|SPLIT_BOTH_CUTOFFS)$",
    )


class PositionRead(BaseModel):
    id: int
    title: str
    code: str
    is_active: bool
    departments: list[DepartmentRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PositionUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    code: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z0-9]+$")
    department_ids: list[int] = Field(default_factory=list)
    is_active: bool = True

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper() if isinstance(value, str) else value


class FixedCompensationRead(BaseModel):
    id: int
    name: str
    amount: Decimal
    month: int
    year: int
    users: list[UserRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FixedCompensationUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(ge=0)
    month: int
    year: int
    user_ids: list[UUID] = Field(default_factory=list)


class FixedCompensationUsersRequest(BaseModel):
    user_ids: list[UUID] = Field(default_factory=list)


class PayslipVariableCompensationRead(BaseModel):
    id: int
    payslip_id: int
    name: str
    amount: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayslipVariableCompensationUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(ge=0)


class PayslipVariableDeductionRead(BaseModel):
    id: int
    payslip_id: int
    name: str
    amount: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayslipVariableDeductionUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(ge=0)


class PayslipRead(BaseModel):
    id: int
    user_id: UUID
    salary: Decimal | None = None
    automatic_deduction_schedule: str | None = None
    period: str | None = None
    released: bool
    release_date: datetime | None = None
    month: int | None = None
    year: int | None = None
    user: UserRead | None = None
    variable_compensations: list[PayslipVariableCompensationRead] = Field(default_factory=list)
    variable_deductions: list[PayslipVariableDeductionRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayslipCreateRequest(BaseModel):
    user_id: UUID
    month: int
    year: int
    period: str = Field(pattern="^(1ST|2ND)$")


class PayslipUpdateRequest(BaseModel):
    salary: Decimal | None = Field(default=None, ge=0)
    released: bool | None = None


class PayslipSummaryRead(BaseModel):
    period: str | None = None
    salary: Decimal | None = None
    compensations: list[FixedCompensationRead] = Field(default_factory=list)
    variable_compensations: list[PayslipVariableCompensationRead] = Field(default_factory=list)
    gross_pay: Decimal | None = None
    variable_deductions: list[PayslipVariableDeductionRead] = Field(default_factory=list)
    total_deductions: Decimal | None = None
    net_salary: Decimal | None = None
    sss_deduction: Decimal | None = None
    philhealth_deduction: Decimal | None = None
    pag_ibig_deduction: Decimal | None = None
    mp2_deduction: Decimal | None = None
    tax_deduction: Decimal | None = None


class PayrollComputationRead(BaseModel):
    gross_pay: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    mandatory_deductions: dict[str, Decimal] = Field(default_factory=dict)
    variable_deductions: Decimal
    mp2_deduction: Decimal
    included_in_total_deductions: bool = True
    notes: list[str] = Field(default_factory=list)


class PayslipSummaryComparisonRead(BaseModel):
    payslip_id: int
    legacy_summary: PayslipSummaryRead
    new_engine: PayrollComputationRead
    differences: dict[str, Decimal] = Field(default_factory=dict)


class ThirteenthMonthAdjustmentRead(BaseModel):
    id: int
    payout_id: int
    type: Literal["ADD", "DEDUCT"]
    label: str
    amount: Decimal
    reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ThirteenthMonthAdjustmentCreateRequest(BaseModel):
    type: Literal["ADD", "DEDUCT"]
    label: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(ge=0)
    reason: str | None = Field(default=None, max_length=500)


class ThirteenthMonthGenerateRequest(BaseModel):
    year: int = Field(ge=2000, le=2200)


class ThirteenthMonthPayoutRead(BaseModel):
    id: int
    user_id: UUID
    year: int
    gross_amount: Decimal
    total_deductions: Decimal
    net_amount: Decimal
    status: Literal["DRAFT", "RELEASED"]
    released_at: datetime | None = None
    user: UserRead | None = None
    adjustments: list[ThirteenthMonthAdjustmentRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
