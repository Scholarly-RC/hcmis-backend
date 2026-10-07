from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from app.schemas.user import UserRead


class LeaveTypeOptionRead(BaseModel):
    value: str
    label: str


class LeaveTypePolicyRead(BaseModel):
    id: UUID
    code: str
    name: str
    max_credits: int
    credit_mode: Literal["incremental", "fixed"]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeaveTypePolicyUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    max_credits: int = Field(ge=0)
    credit_mode: Literal["incremental", "fixed"]


class LeaveCreditUpsertRequest(BaseModel):
    credits: float = Field(ge=0)


class LeaveCreditRead(BaseModel):
    user_id: UUID
    leave_type: str | None = None
    credits: float
    used_credits: float
    remaining_credits: float
    user: UserRead | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LeaveRequestCreateRequest(BaseModel):
    leave_date: date
    leave_type: str = Field(min_length=1, max_length=24)
    duration: Literal["FULL_DAY", "FIRST_HALF", "SECOND_HALF"] = "FULL_DAY"
    info: str | None = None


class LeaveRequestReviewRequest(BaseModel):
    response: Literal["APPROVE", "REJECT"]
    approval_type: Literal["PAID", "NON_PAID"] | None = None


class LeaveRequestApproverRead(BaseModel):
    id: int
    leave_request_id: int
    approver_id: UUID
    status: str
    acted_at: datetime | None = None
    approver: UserRead | None = None

    model_config = ConfigDict(from_attributes=True)


class LeaveRequestRead(BaseModel):
    id: int
    user_id: UUID
    leave_date: date
    leave_type: str
    duration: Literal["FULL_DAY", "FIRST_HALF", "SECOND_HALF"] = "FULL_DAY"
    approval_type: Literal["PAID", "NON_PAID"] | None = None
    info: str | None = None
    first_approver_id: UUID | None = None
    first_approver_status: str
    first_approver_at: datetime | None = None
    second_approver_id: UUID | None = None
    second_approver_status: str | None = None
    second_approver_at: datetime | None = None
    escalated_to_backup_at: datetime | None = None
    escalated_to_backup_by_id: UUID | None = None
    status: str
    user: UserRead | None = None
    first_approver: UserRead | None = None
    second_approver: UserRead | None = None
    approver_pool: list[LeaveRequestApproverRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_validator("duration", mode="before")
    @classmethod
    def default_missing_duration(cls, value):
        return "FULL_DAY" if value is None else value

    model_config = ConfigDict(from_attributes=True)
