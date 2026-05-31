"""Authentication request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class AuthUserResponse(BaseModel):
    id: int
    username: str
    email: str | None = None
    is_admin: bool = False
    created_at: datetime
    last_active_at: datetime | None = None


class AuthRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100, pattern=r"^[\w.\-]+$")
    email: str | None = Field(None, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("email must contain @")
        return normalized


class AuthLoginRequest(BaseModel):
    login: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("login")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        return value.strip()


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserResponse


class AuthLogoutResponse(BaseModel):
    logged_out: bool = True
