"""Database engines and session factories."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from jarvis.core.settings import get_settings


settings = get_settings()

async_engine = create_async_engine(settings.sqlalchemy_async_url, echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

sync_engine = create_engine(settings.sqlalchemy_sync_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)

