"""Router composition for Layer 6 API v1."""

from __future__ import annotations

from fastapi import APIRouter

from jarvis.app.api.v1 import admin, auth, chat, digest, entities, feedback, health, news, profile, search

api_v1_router = APIRouter()

api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
api_v1_router.include_router(news.router, prefix="/api/v1/news", tags=["news"])
api_v1_router.include_router(search.router, prefix="/api/v1/search", tags=["search"])
api_v1_router.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"])
api_v1_router.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])
api_v1_router.include_router(digest.router, tags=["digest"])
api_v1_router.include_router(profile.router, prefix="/api/v1/profile", tags=["profile"])
api_v1_router.include_router(entities.router, prefix="/api/v1/entities", tags=["entities"])
api_v1_router.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
