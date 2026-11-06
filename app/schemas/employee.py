from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Email = Annotated[EmailStr, Field(max_length=254)]


class EmployeeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("email", check_fields=False)
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower() if value is not None else None


class EmployeeCreate(EmployeeInput):
    full_name: Name
    email: Email
    department: Label | None = None
    job_title: Label | None = None
    is_active: bool = True


class EmployeeUpdate(EmployeeInput):
    full_name: Name | None = None
    email: Email | None = None
    department: Label | None = None
    job_title: Label | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("full_name", "email", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    department: str | None
    job_title: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
