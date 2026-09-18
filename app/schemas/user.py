from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import EmailStr
from pydantic import Field
from pydantic import field_serializer
from pydantic import field_validator
from pydantic import model_validator

from app.services.profile_photo_storage import get_profile_photo_read_url
from app.schemas.department import DepartmentRead

EMPLOYEE_TYPE_VALUES = {
    "RANK_AND_FILE",
    "SUPERVISOR",
    "MANAGER",
    "OFFICER",
}
EMPLOYMENT_STATUS_VALUES = {
    "CONTRACTUAL",
    "PROVISIONARY",
    "REGULAR",
}


def normalize_employee_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized == "":
        return None
    if normalized not in EMPLOYEE_TYPE_VALUES:
        raise ValueError(
            "Employee type must be one of: RANK_AND_FILE, SUPERVISOR, MANAGER, OFFICER."
        )
    return normalized


def normalize_employment_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized == "":
        return None
    if normalized not in EMPLOYMENT_STATUS_VALUES:
        raise ValueError(
            "Employment status must be one of: CONTRACTUAL, PROVISIONARY, REGULAR."
        )
    return normalized


class UserRead(BaseModel):
    id: UUID
    email: str
    username: str | None = None
    first_name: str
    last_name: str
    middle_name: str | None = None
    gender: str | None = None
    highest_education_level: str | None = None
    highest_education_program: str | None = None
    civil_status: str | None = None
    religion: str | None = None
    position_id: int | None = None
    monthly_salary: Decimal | None = Field(default=None, ge=0)
    employee_number: str | None = None
    biometric_uid: int | None = None
    role: str | None = None
    employee_type: str | None = None
    employment_status: str | None = None
    department_id: int | None = None
    level_1_approver_id: UUID | None = None
    level_2_approver_id: UUID | None = None
    department: DepartmentRead | None = None
    phone_number: str | None = None
    address: str | None = None
    date_of_birth: date | None = None
    date_of_hiring: date | None = None
    resignation_date: date | None = None
    profile_picture_url: str | None = None
    can_modify_shift: bool
    must_change_password: bool
    temporary_password_expires_at: datetime | None = None
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("must_change_password", mode="before")
    @classmethod
    def normalize_must_change_password(cls, value: object) -> bool:
        if value is None:
            return False
        return bool(value)

    @field_serializer("profile_picture_url")
    def serialize_profile_picture_url(self, value: str | None) -> str | None:
        return get_profile_photo_read_url(value)


class UserWithCapabilitiesRead(UserRead):
    capabilities: list[str] = Field(default_factory=list)


class UserEmploymentMovementRead(BaseModel):
    id: int
    user_id: UUID
    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    change_batch_id: UUID
    changed_by: UUID | None = None
    effective_date: date | None = None
    changed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserCreateRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=1)
    password: str = Field(min_length=8)
    first_name: str = ""
    last_name: str = ""
    middle_name: str | None = None
    gender: str | None = None
    highest_education_level: str | None = None
    highest_education_program: str | None = None
    civil_status: str | None = None
    religion: str | None = None
    position_id: int | None = None
    monthly_salary: Decimal | None = Field(default=None, ge=0)
    assignment_effective_from: date | None = None
    assignment_change_reason: str | None = None
    employee_number: str | None = None
    biometric_uid: int | None = None
    role: str | None = None
    employee_type: str | None = None
    employment_status: str | None = None
    department_id: int | None = None
    level_1_approver_id: UUID | None = None
    level_2_approver_id: UUID | None = None
    phone_number: str | None = None
    address: str | None = None
    date_of_birth: date | None = None
    date_of_hiring: date | None = None
    resignation_date: date | None = None
    profile_picture_url: str | None = None
    can_modify_shift: bool = False
    is_active: bool = True
    is_superuser: bool = False

    @field_validator("username")
    @classmethod
    def validate_username_required(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("Username is required.")
        return value

    @field_validator("employee_type", mode="before")
    @classmethod
    def normalize_employee_type_value(cls, value: str | None) -> str | None:
        return normalize_employee_type(value)

    @field_validator("employment_status", mode="before")
    @classmethod
    def normalize_employment_status_value(cls, value: str | None) -> str | None:
        return normalize_employment_status(value)

    @model_validator(mode="after")
    def validate_approver_uniqueness(self) -> "UserCreateRequest":
        if (
            self.level_1_approver_id is not None
            and self.level_2_approver_id is not None
            and self.level_1_approver_id == self.level_2_approver_id
        ):
            raise ValueError("Level 1 and Level 2 approvers must be different users.")
        return self


class UserUpdateRequest(BaseModel):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    gender: str | None = None
    highest_education_level: str | None = None
    highest_education_program: str | None = None
    civil_status: str | None = None
    religion: str | None = None
    position_id: int | None = None
    monthly_salary: Decimal | None = Field(default=None, ge=0)
    assignment_effective_from: date | None = None
    assignment_change_reason: str | None = None
    employee_number: str | None = None
    biometric_uid: int | None = None
    role: str | None = None
    employee_type: str | None = None
    employment_status: str | None = None
    department_id: int | None = None
    level_1_approver_id: UUID | None = None
    level_2_approver_id: UUID | None = None
    phone_number: str | None = None
    address: str | None = None
    date_of_birth: date | None = None
    date_of_hiring: date | None = None
    resignation_date: date | None = None
    profile_picture_url: str | None = None
    can_modify_shift: bool | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None

    @field_validator("employee_type", mode="before")
    @classmethod
    def normalize_employee_type_value(cls, value: str | None) -> str | None:
        return normalize_employee_type(value)

    @field_validator("employment_status", mode="before")
    @classmethod
    def normalize_employment_status_value(cls, value: str | None) -> str | None:
        return normalize_employment_status(value)

    @model_validator(mode="after")
    def validate_approver_uniqueness(self) -> "UserUpdateRequest":
        if (
            self.level_1_approver_id is not None
            and self.level_2_approver_id is not None
            and self.level_1_approver_id == self.level_2_approver_id
        ):
            raise ValueError("Level 1 and Level 2 approvers must be different users.")
        return self


class UserBiometricUpdateRequest(BaseModel):
    biometric_uid: int | None = None


class UserProfileUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    gender: str | None = None
    highest_education_level: str | None = None
    highest_education_program: str | None = None
    civil_status: str | None = None
    religion: str | None = None
    phone_number: str | None = None
    address: str | None = None
    date_of_birth: date | None = None
    date_of_hiring: date | None = None
    profile_picture_url: str | None = None
