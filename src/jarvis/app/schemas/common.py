"""Общие Pydantic-схемы для Layer 6."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Pagination(BaseModel):
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str
    code: str = "error"
