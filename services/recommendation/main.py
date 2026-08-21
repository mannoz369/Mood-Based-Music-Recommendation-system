from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import get_event_settings, get_recommendation_settings
from services.events import create_event_producer
from services.recommendation.cache import RecommendationCache
from services.recommendation.service import RecommendationService
from services.recommendation.jamendo_client import JamendoClient, JamendoError


app = FastAPI(
    title="Emotion Music Recommendation Service",
    version="0.1.0",
    description="Maps detected emotions to Jamendo-backed music recommendations.",
)

settings = get_recommendation_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class EmotionRecommendationRequest(BaseModel):
    emotion: str
    limit: int | None = None
    user_id: str | None = None
    language: str | None = None
    request_seed: str | None = None


class PlaybackEventRequest(BaseModel):
    event_type: str
    track_id: str
    emotion: str | None = None
    provider: str | None = "jamendo"
    user_id: str | None = None


@lru_cache(maxsize=1)
def get_recommendation_service():
    service_settings = get_recommendation_settings()
    return RecommendationService(
        JamendoClient(service_settings),
        service_settings,
        cache=RecommendationCache(
            service_settings.redis_url,
            namespace=service_settings.redis_namespace,
            fail_open=service_settings.redis_fail_open,
        ),
        event_producer=create_event_producer(get_event_settings()),
    )


@app.get("/health")
async def health():
    recommendation_settings = get_recommendation_settings()
    recommendation_service = get_recommendation_service()
    return {
        "status": "ok",
        "service": recommendation_settings.service_name,
        "provider": "jamendo",
        "jamendo_configured": bool(recommendation_settings.jamendo_client_id),
        "features": {
            "dynamic_query": True,
            "jamendo_query_console_print": True,
            "recent_recommended_track_memory": True,
            "alternate_query_fallback": True,
        },
        "cache": await recommendation_service.cache_status(),
        "cache_ttl_seconds": recommendation_settings.cache_ttl_seconds,
        "cooldown_seconds": recommendation_settings.cooldown_seconds,
    }


@app.get("/recommendation/intents")
async def intents():
    return get_recommendation_service().metadata()


@app.get("/recommendation/current-emotion")
async def current_emotion(user_id: str | None = Query(default=None)):
    emotion = await get_recommendation_service().current_emotion(user_id or "anonymous")
    return {"emotion": emotion}


@app.post("/recommendation/from-emotion")
async def from_emotion(
    request: EmotionRecommendationRequest,
):
    try:
        return await get_recommendation_service().from_emotion(
            request.emotion,
            limit=request.limit,
            user_id=request.user_id or "anonymous",
            language=request.language,
            request_seed=request.request_seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except JamendoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/recommendation/playback/event")
async def playback_event(request: PlaybackEventRequest):
    try:
        return await get_recommendation_service().record_playback_event(
            request.event_type,
            request.track_id,
            user_id=request.user_id or "anonymous",
            emotion=request.emotion,
            provider=request.provider or "jamendo",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/recommendation/from-emotion")
async def from_emotion_query(
    emotion: str,
    limit: int | None = Query(default=None, ge=1, le=25),
    user_id: str | None = Query(default=None),
    language: str | None = Query(default=None),
    request_seed: str | None = Query(default=None),
):
    try:
        return await get_recommendation_service().from_emotion(
            emotion,
            limit=limit,
            user_id=user_id or "anonymous",
            language=language,
            request_seed=request_seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except JamendoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
