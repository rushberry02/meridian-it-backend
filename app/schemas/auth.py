from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    role: Literal["employee", "admin"] | None = None
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class PasswordSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def not_blank(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("Password must contain non-whitespace characters")
        return value


class UserCreate(PasswordSet):
    employee_id: int = Field(gt=0, le=2147483647)
    role: Literal["employee", "admin"] = "employee"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: SecretStr = Field(min_length=1, max_length=256)


class UserRead(BaseModel):
    id: int
    employee_id: int
    role: str
    full_name: str
    email: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime
    session_expires_at: datetime
    user: UserRead


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int = Field(gt=0, le=2147483647)
    role: Literal["employee", "admin"] = "employee"


class PasswordSetup(PasswordSet):
    token: SecretStr = Field(min_length=32, max_length=256)
