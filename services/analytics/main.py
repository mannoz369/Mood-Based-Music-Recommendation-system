from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException, Query, status

from config import get_analytics_settings
from services.analytics.repository import MongoAnalyticsRepository
from services.analytics.service import AnalyticsService


app = FastAPI(
    title="Emotion Music Analytics Service",
    version="0.1.0",
    description="Read APIs for mood, recommendation, and playback analytics.",
)


@lru_cache(maxsize=1)
def get_analytics_service():
    settings = get_analytics_settings()
    return AnalyticsService(MongoAnalyticsRepository(settings), settings)


def _trusted_user_id(x_user_id: str | None = Header(default=None)):
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing trusted user id.",
        )

    return x_user_id


async def _ready_service():
    try:
        service = get_analytics_service()
        await service.ensure_ready()
        return service
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@app.get("/health")
async def health():
    settings = get_analytics_settings()

    if not settings.mongodb_uri:
        return {
            "status": "degraded",
            "service": settings.service_name,
            "database": "unconfigured",
            "detail": "MONGODB_URI is not configured.",
        }

    try:
        service = get_analytics_service()
        await service.ensure_ready()
        await service.health_check()
    except Exception as exc:
        return {
            "status": "degraded",
            "service": settings.service_name,
            "database": "unavailable",
            "detail": str(exc),
        }

    return {
        "status": "ok",
        "service": settings.service_name,
        "database": settings.mongodb_database,
    }


@app.get("/analytics/me/moods")
async def my_moods(
    user_id: str = Header(alias="x-user-id"),
    limit: int = Query(default=50, ge=1, le=200),
):
    service = await _ready_service()
    return await service.moods_for_user(user_id, limit=limit)


@app.get("/analytics/me/recommendations")
async def my_recommendations(
    user_id: str = Header(alias="x-user-id"),
    limit: int = Query(default=50, ge=1, le=200),
):
    service = await _ready_service()
    return await service.recommendations_for_user(user_id, limit=limit)


@app.get("/analytics/me/playback")
async def my_playback(
    user_id: str = Header(alias="x-user-id"),
    limit: int = Query(default=50, ge=1, le=200),
):
    service = await _ready_service()
    return await service.playback_for_user(user_id, limit=limit)


@app.get("/analytics/me/summary")
async def my_summary(user_id: str = Header(alias="x-user-id")):
    service = await _ready_service()
    return await service.summary_for_user(user_id)
