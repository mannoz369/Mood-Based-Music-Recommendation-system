import asyncio
from dataclasses import replace

from fastapi.testclient import TestClient

from config import get_analytics_settings, get_event_settings
from services.analytics.consumer import AnalyticsEventConsumer
from services.analytics import main
from services.analytics.service import AnalyticsService


class InMemoryAnalyticsRepository:
    def __init__(self):
        self.ready = False
        self.events = []
        self.moods = []
        self.recommendations = []
        self.playbacks = []

    async def ensure_indexes(self):
        self.ready = True

    async def health_check(self):
        return None

    async def store_event(self, document):
        self.events.append(document)
        return document

    async def store_mood_timeline(self, document):
        self.moods.append(document)
        return document

    async def store_recommendation_history(self, document):
        self.recommendations.append(document)
        return document

    async def store_playback_history(self, document):
        self.playbacks.append(document)
        return document

    async def list_moods(self, user_id, limit=50):
        return self.moods[:limit]

    async def list_recommendations(self, user_id, limit=50):
        return self.recommendations[:limit]

    async def list_playback(self, user_id, limit=50):
        return self.playbacks[:limit]


def _settings():
    return replace(
        get_analytics_settings(),
        mongodb_uri="mongodb://example.invalid",
    )


def _service(repository=None):
    repo = repository or InMemoryAnalyticsRepository()
    return AnalyticsService(repo, _settings()), repo


def test_analytics_service_stores_raw_and_mood_event():
    async def run():
        service, repo = _service()

        result = await service.handle_event(
            {
                "event_id": "event-1",
                "event_type": "emotion.detected",
                "schema_version": 1,
                "occurred_at": "2026-08-21T00:00:00Z",
                "user_id": "user-1",
                "correlation_id": "capture-1",
                "source_service": "api-gateway",
                "payload": {
                    "emotion": "Happy",
                    "confidence": 0.91,
                    "face": {"x": 1, "y": 2},
                },
            }
        )

        return result, repo

    result, repo = asyncio.run(run())

    assert result["collections"] == ["analytics_events", "user_mood_timeline"]
    assert repo.events[0]["event_id"] == "event-1"
    assert repo.moods[0]["user_id"] == "user-1"
    assert repo.moods[0]["emotion"] == "Happy"
    assert repo.moods[0]["confidence"] == 0.91


def test_analytics_service_stores_recommendation_history():
    async def run():
        service, repo = _service()

        result = await service.handle_event(
            {
                "event_id": "event-2",
                "event_type": "recommendation.generated",
                "schema_version": 1,
                "occurred_at": "2026-08-21T00:01:00Z",
                "user_id": "user-1",
                "source_service": "recommendation-service",
                "payload": {
                    "emotion": "Happy",
                    "language": "en",
                    "query": "funk bright groove upbeat",
                    "dynamic_profile": {"variant": "funk-groove"},
                    "cache": {"hit": False, "key": "recommendations:user-1"},
                    "track_ids": ["track-1", "track-2"],
                    "provider": "jamendo",
                },
            }
        )

        return result, repo

    result, repo = asyncio.run(run())

    assert result["collections"] == [
        "analytics_events",
        "user_recommendation_history",
    ]
    assert repo.recommendations[0]["event_type"] == "recommendation.generated"
    assert repo.recommendations[0]["query"] == "funk bright groove upbeat"
    assert repo.recommendations[0]["track_ids"] == ["track-1", "track-2"]


def test_analytics_service_stores_playback_history():
    async def run():
        service, repo = _service()

        result = await service.handle_event(
            {
                "event_id": "event-3",
                "event_type": "playback.event",
                "schema_version": 1,
                "occurred_at": "2026-08-21T00:02:00Z",
                "user_id": "user-1",
                "source_service": "recommendation-service",
                "payload": {
                    "event_type": "skipped",
                    "track_id": "track-1",
                    "emotion": "Happy",
                    "provider": "jamendo",
                },
            }
        )

        return result, repo

    result, repo = asyncio.run(run())

    assert result["collections"] == ["analytics_events", "user_playback_history"]
    assert repo.playbacks[0]["action"] == "skipped"
    assert repo.playbacks[0]["track_id"] == "track-1"


def test_analytics_consumer_dispatches_json_bytes():
    async def run():
        service, repo = _service()
        consumer = AnalyticsEventConsumer(service, get_event_settings())

        result = await consumer.handle_event(
            b"""
            {
              "event_id": "event-4",
              "event_type": "camera.capture",
              "schema_version": 1,
              "occurred_at": "2026-08-21T00:03:00Z",
              "user_id": "user-1",
              "source_service": "api-gateway",
              "payload": {"route": "/api/emotion/detect"}
            }
            """
        )

        return result, repo

    result, repo = asyncio.run(run())

    assert result["collections"] == ["analytics_events"]
    assert repo.events[0]["event_type"] == "camera.capture"


def test_analytics_api_returns_only_trusted_user_history(monkeypatch):
    service, repo = _service()
    repo.moods.append(
        {
            "event_id": "event-1",
            "user_id": "auth-user",
            "emotion": "Happy",
            "occurred_at": "2026-08-21T00:00:00Z",
        }
    )
    monkeypatch.setattr(main, "get_analytics_service", lambda: service)
    client = TestClient(main.app)

    response = client.get(
        "/analytics/me/moods",
        headers={"x-user-id": "auth-user"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "auth-user",
        "moods": [
            {
                "event_id": "event-1",
                "user_id": "auth-user",
                "emotion": "Happy",
                "occurred_at": "2026-08-21T00:00:00Z",
            }
        ],
    }


def test_analytics_api_summary_requires_trusted_user_id(monkeypatch):
    service, _repo = _service()
    monkeypatch.setattr(main, "get_analytics_service", lambda: service)
    client = TestClient(main.app)

    response = client.get("/analytics/me/summary")

    assert response.status_code == 422
