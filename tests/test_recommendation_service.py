import asyncio
from dataclasses import replace

from fastapi.testclient import TestClient

from config import get_recommendation_settings
from services.recommendation import main
from services.recommendation.cache import RecommendationCache
from services.recommendation.intents import get_profile_variants_for_emotion
from services.recommendation.service import RecommendationService
from services.recommendation.jamendo_client import JamendoClient, JamendoError


class FakeJamendoClient:
    def __init__(self, tracks=None):
        self.tracks = tracks or [
            {
                "id": "track-1",
                "name": "Bright Song",
                "artists": ["Artist"],
                "uri": "https://audio.example/track-1.mp3",
                "provider": "jamendo",
            },
            {
                "id": "track-1",
                "name": "Duplicate Song",
                "artists": ["Artist"],
                "uri": "https://audio.example/track-1.mp3",
                "provider": "jamendo",
            },
            {
                "id": "track-2",
                "name": "Second Song",
                "artists": ["Artist"],
                "uri": "https://audio.example/track-2.mp3",
                "provider": "jamendo",
            },
        ]
        self.last_query = None
        self.last_language = None
        self.last_limit = None

    async def search_tracks(self, query, limit, language=None):
        self.last_query = query
        self.last_language = language
        self.last_limit = limit
        return self.tracks


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.lists = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value

        if ex is not None:
            self.ttls[key] = ex

        return True

    async def incr(self, key):
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = str(value)
        return value

    async def expire(self, key, ttl_seconds):
        self.ttls[key] = ttl_seconds
        return True

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key, start, stop):
        values = self.lists.get(key, [])
        end = None if stop == -1 else stop + 1
        self.lists[key] = values[start:end]
        return True

    async def lrange(self, key, start, stop):
        values = self.lists.get(key, [])
        end = None if stop == -1 else stop + 1
        return values[start:end]


def _settings():
    return replace(
        get_recommendation_settings(),
        service_name="recommendation-service",
        default_limit=10,
    )


def _client(monkeypatch, music_client=None):
    settings = _settings()
    fake_music = music_client or FakeJamendoClient()
    service = RecommendationService(fake_music, settings)
    monkeypatch.setattr(main, "get_recommendation_service", lambda: service)
    monkeypatch.setattr(main, "get_recommendation_settings", lambda: settings)
    return TestClient(main.app), fake_music


def test_intents_returns_supported_emotions(monkeypatch):
    client, _jamendo = _client(monkeypatch)

    response = client.get("/recommendation/intents")

    assert response.status_code == 200
    assert "Happy" in response.json()["supported_emotions"]
    assert response.json()["intents"]["Sad"]["intent"] == "comfort"


def test_from_emotion_maps_emotion_to_jamendo_search(monkeypatch):
    client, jamendo = _client(monkeypatch)

    response = client.post(
        "/recommendation/from-emotion",
        json={"emotion": "Happy", "limit": 2, "request_seed": "2026-08-18T10:15"},
    )

    assert response.status_code == 200
    body = response.json()
    happy_queries = {variant["query"] for variant in get_profile_variants_for_emotion("Happy")}
    assert body["emotion"] == "Happy"
    assert body["intent"]["intent"] == "amplify"
    assert body["provider"] == "jamendo"
    assert body["language"] == "any"
    assert body["query"] in happy_queries
    assert body["query"] == jamendo.last_query
    assert jamendo.last_limit == 6
    assert body["query_seed"] == "2026-08-18T10:15:anonymous:Happy:any::"
    assert body["dynamic_profile"]["intent"] == "amplify"
    assert body["dynamic_profile"]["variant"]
    assert [track["id"] for track in body["tracks"]] == ["track-1", "track-2"]


def test_from_emotion_passes_language_preference_to_jamendo(monkeypatch):
    client, jamendo = _client(monkeypatch)

    response = client.post(
        "/recommendation/from-emotion",
        json={"emotion": "Happy", "limit": 2, "language": "te"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "te"
    assert jamendo.last_language == "te"


def test_from_emotion_varies_query_with_request_seed(monkeypatch):
    client, jamendo = _client(monkeypatch)

    first_response = client.post(
        "/recommendation/from-emotion",
        json={"emotion": "Happy", "limit": 2, "language": "en", "request_seed": "fresh-1"},
    )
    first_query = jamendo.last_query
    second_response = client.post(
        "/recommendation/from-emotion",
        json={"emotion": "Happy", "limit": 2, "language": "en", "request_seed": "fresh-2"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_query != jamendo.last_query
    assert first_response.json()["dynamic_profile"]["variant"] == "summer-pop"
    assert second_response.json()["dynamic_profile"]["variant"] == "funk-groove"
    assert first_response.json()["cache"]["key"] != second_response.json()["cache"]["key"]


def test_from_emotion_rejects_unknown_emotion(monkeypatch):
    client, _jamendo = _client(monkeypatch)

    response = client.post(
        "/recommendation/from-emotion",
        json={"emotion": "Bored"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported emotion: Bored"


def test_jamendo_failures_are_preserved(monkeypatch):
    class FailingJamendoClient:
        async def search_tracks(self, query, limit, language=None):
            raise JamendoError(503, "JAMENDO_CLIENT_ID is not configured.")

    client, _jamendo = _client(monkeypatch, FailingJamendoClient())

    response = client.post(
        "/recommendation/from-emotion",
        json={"emotion": "Neutral"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "JAMENDO_CLIENT_ID is not configured."


def test_cache_is_disabled_when_redis_url_is_not_configured():
    async def run():
        cache = RecommendationCache(None)

        assert await cache.get_json("missing") is None
        assert await cache.set_json("value", {"ok": True}, ttl_seconds=30) is False
        assert await cache.increment_counter("rate-limit:test:user", ttl_seconds=60) is None
        assert await cache.get_recent_track_ids("user-1") == []

        status = await cache.status()
        assert status["enabled"] is False
        assert status["fail_open"] is True

    asyncio.run(run())


def test_cache_supports_json_text_counters_ttl_and_cooldowns():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis

        assert await cache.set_json("payload", {"emotion": "Happy"}, ttl_seconds=30)
        assert await cache.get_json("payload") == {"emotion": "Happy"}
        assert redis.ttls["test:payload"] == 30

        assert await cache.set_text("message", "hello", ttl_seconds=10)
        assert await cache.get_text("message") == "hello"
        assert await cache.ttl("message") == 10

        key = cache.rate_limit_key("emotion", "User 1")
        assert key == "rate-limit:emotion:user-1"
        assert await cache.increment_counter(key, ttl_seconds=60) == 1
        assert await cache.increment_counter(key, ttl_seconds=60) == 2
        assert await cache.ttl(key) == 60

        assert await cache.set_current_emotion("User 1", "Happy", ttl_seconds=45)
        assert await cache.get_current_emotion("User 1") == {"emotion": "Happy"}

        assert await cache.set_cooldown("User 1", "Happy", ttl_seconds=45)
        cooldown = await cache.get_cooldown("User 1", "Happy")
        assert cooldown == {"active": True, "ttl_seconds": 45}

    asyncio.run(run())


def test_cache_maintains_bounded_recent_track_lists():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis

        assert await cache.remember_recent_track_ids(
            "User 1",
            ["track-1", "track-2", "track-3"],
            kind="recommended",
            limit=2,
            ttl_seconds=90,
        )

        assert await cache.get_recent_track_ids("User 1", kind="recommended") == [
            "track-3",
            "track-2",
        ]
        assert redis.ttls["test:recent-recommended-tracks:user-1"] == 90

        assert await cache.remember_recent_track_id(
            "User 1",
            "played-1",
            kind="played",
            limit=50,
            ttl_seconds=120,
        )
        assert await cache.get_recent_track_ids("User 1", kind="played") == ["played-1"]

    asyncio.run(run())


def test_recommendation_service_writes_operational_cache_state():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis
        service = RecommendationService(FakeJamendoClient(), _settings(), cache=cache)

        response = await service.from_emotion("Happy", limit=2, user_id="User 1")

        assert response["cache"]["hit"] is False
        assert await cache.get_current_emotion("User 1") == {"emotion": "Happy"}
        assert await cache.get_cooldown("User 1", "Happy") == {
            "active": True,
            "ttl_seconds": service.settings.cooldown_seconds,
        }

    asyncio.run(run())


def test_current_emotion_returns_cached_user_mood():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis
        service = RecommendationService(FakeJamendoClient(), _settings(), cache=cache)

        assert await service.current_emotion("User 1") is None

        await cache.set_current_emotion("User 1", "Happy", ttl_seconds=60)

        assert await service.current_emotion("User 1") == "Happy"

    asyncio.run(run())


def test_current_emotion_endpoint_returns_cached_user_mood(monkeypatch):
    class FakeService:
        async def current_emotion(self, user_id):
            assert user_id == "auth-user"
            return "Happy"

    monkeypatch.setattr(main, "get_recommendation_service", lambda: FakeService())
    client = TestClient(main.app)

    response = client.get("/recommendation/current-emotion?user_id=auth-user")

    assert response.status_code == 200
    assert response.json() == {"emotion": "Happy"}


def test_playback_event_updates_recent_played_track_memory():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis
        service = RecommendationService(FakeJamendoClient(), _settings(), cache=cache)

        response = await service.record_playback_event(
            "started",
            "track-123",
            user_id="User 1",
            emotion="Happy",
            provider="jamendo",
        )

        assert response == {
            "status": "ok",
            "event_type": "started",
            "track_id": "track-123",
            "emotion": "Happy",
            "provider": "jamendo",
        }
        assert await cache.get_recent_track_ids("User 1", kind="played") == ["track-123"]

    asyncio.run(run())


def test_playback_event_rejects_invalid_event_type():
    async def run():
        service = RecommendationService(FakeJamendoClient(), _settings())

        try:
            await service.record_playback_event("replayed", "track-123", user_id="User 1")
        except ValueError as exc:
            assert str(exc) == "Unsupported playback event type: replayed"
            return

        raise AssertionError("Expected invalid playback event to fail.")

    asyncio.run(run())


def test_playback_event_endpoint_records_event(monkeypatch):
    class FakeService:
        async def record_playback_event(self, event_type, track_id, user_id, emotion=None, provider="jamendo"):
            assert event_type == "started"
            assert track_id == "track-123"
            assert user_id == "auth-user"
            assert emotion == "Happy"
            assert provider == "jamendo"
            return {"status": "ok", "event_type": event_type, "track_id": track_id}

    monkeypatch.setattr(main, "get_recommendation_service", lambda: FakeService())
    client = TestClient(main.app)

    response = client.post(
        "/recommendation/playback/event",
        json={
            "event_type": "started",
            "track_id": "track-123",
            "user_id": "auth-user",
            "emotion": "Happy",
            "provider": "jamendo",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recommendation_service_filters_recent_tracks_and_remembers_returned_tracks():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis
        tracks = [
            {"id": "track-1", "name": "Recent Recommended", "uri": "https://audio.example/1.mp3"},
            {"id": "track-2", "name": "Recent Played", "uri": "https://audio.example/2.mp3"},
            {"id": "track-3", "name": "Fresh One", "uri": "https://audio.example/3.mp3"},
            {"id": "track-4", "name": "Fresh Two", "uri": "https://audio.example/4.mp3"},
        ]
        music_client = FakeJamendoClient(tracks=tracks)
        service = RecommendationService(music_client, _settings(), cache=cache)

        await cache.remember_recent_track_id("User 1", "track-1", kind="recommended")
        await cache.remember_recent_track_id("User 1", "track-2", kind="played")

        response = await service.from_emotion(
            "Happy",
            limit=2,
            user_id="User 1",
            request_seed="fresh-filter",
        )

        assert music_client.last_limit == 6
        assert [track["id"] for track in response["tracks"]] == ["track-3", "track-4"]
        recent_recommended = await cache.get_recent_track_ids("User 1", kind="recommended")
        assert recent_recommended[:2] == [
            "track-4",
            "track-3",
        ]

    asyncio.run(run())


def test_recommendation_service_falls_back_when_recent_filter_removes_everything():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis
        tracks = [
            {"id": "track-1", "name": "Recent Recommended", "uri": "https://audio.example/1.mp3"},
            {"id": "track-2", "name": "Recent Played", "uri": "https://audio.example/2.mp3"},
        ]
        service = RecommendationService(FakeJamendoClient(tracks=tracks), _settings(), cache=cache)

        await cache.remember_recent_track_id("User 1", "track-1", kind="recommended")
        await cache.remember_recent_track_id("User 1", "track-2", kind="played")

        response = await service.from_emotion(
            "Happy",
            limit=2,
            user_id="User 1",
            request_seed="fallback-filter",
        )

        assert [track["id"] for track in response["tracks"]] == ["track-1", "track-2"]

    asyncio.run(run())


def test_recommendation_service_uses_cache_without_calling_jamendo(capsys):
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis
        music_client = FakeJamendoClient()
        service = RecommendationService(music_client, _settings(), cache=cache)
        intent = service.metadata()["intents"]["Happy"]
        query_context = service._dynamic_query_context(
            "Happy",
            intent,
            "User 1",
            None,
            request_seed="same-query",
        )
        cache_key = service._recommendation_cache_key(
            "User 1",
            "Happy",
            2,
            None,
            query_context["query_signature"],
        )
        await cache.set_json(
            cache_key,
            {
                "emotion": "Happy",
                "intent": intent,
                "provider": "jamendo",
                "language": "any",
                "query": query_context["query"],
                "query_seed": query_context["query_seed"],
                "dynamic_profile": query_context["dynamic_profile"],
                "tracks": [{"id": "cached-track", "name": "Cached Song"}],
            },
            ttl_seconds=60,
        )
        response = await service.from_emotion(
            "Happy",
            limit=2,
            user_id="User 1",
            request_seed="same-query",
        )

        return response, query_context["query"]

    response, query = asyncio.run(run())
    printed_lines = [line for line in capsys.readouterr().out.splitlines() if line]

    assert response["cache"]["hit"] is True
    assert printed_lines == []


def test_recommendation_service_remembers_recent_tracks_on_cache_hit():
    async def run():
        redis = FakeRedis()
        cache = RecommendationCache("redis://test", namespace="test")
        cache._redis = redis
        service = RecommendationService(FakeJamendoClient(), _settings(), cache=cache)

        first_response = await service.from_emotion(
            "Happy",
            limit=2,
            user_id="User 1",
            request_seed="cached-memory",
        )
        redis.lists["test:recent-recommended-tracks:user-1"] = []

        cached_response = await service.from_emotion(
            "Happy",
            limit=2,
            user_id="User 1",
            request_seed="cached-memory",
        )
        recent_recommended = await cache.get_recent_track_ids("User 1", kind="recommended")

        assert cached_response["cache"]["hit"] is True
        assert recent_recommended == [
            track["id"] for track in reversed(first_response["tracks"])
        ]

    asyncio.run(run())


def test_jamendo_client_prints_only_query_before_request(monkeypatch, capsys):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"headers": {"status": "success"}, "results": []}

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, params):
            return FakeResponse()

    settings = replace(
        _settings(),
        jamendo_client_id="client-id",
    )

    monkeypatch.setattr("services.recommendation.jamendo_client.httpx.AsyncClient", FakeAsyncClient)

    async def run():
        client = JamendoClient(settings)
        await client.search_tracks("funk bright groove upbeat", 5, language="en")

    asyncio.run(run())

    assert capsys.readouterr().out.splitlines() == ["funk bright groove upbeat"]
