import httpx
import pytest
from fastapi.testclient import TestClient

from services.api_gateway import main


def _json_response(status_code, payload):
    return httpx.Response(status_code, json=payload)


AUTH_HEADER = {"Authorization": "Bearer token"}
AUTH_USER = {"id": "auth-user", "email": "user@example.com"}


def _auth_me_response():
    return _json_response(200, {"user": AUTH_USER})


class FakeRateLimitCache:
    def __init__(self, unavailable=False):
        self.unavailable = unavailable
        self.counts = {}
        self.ttls = {}

    async def status(self):
        if self.unavailable:
            return {
                "enabled": True,
                "available": False,
                "detail": "Redis unavailable",
                "fail_open": True,
            }

        return {
            "enabled": True,
            "available": True,
            "detail": "connected",
            "fail_open": True,
        }

    async def increment_counter(self, key, ttl_seconds):
        if self.unavailable:
            return None

        self.counts[key] = self.counts.get(key, 0) + 1
        self.ttls.setdefault(key, ttl_seconds)
        return self.counts[key]

    async def ttl(self, key):
        return self.ttls.get(key, 60)

    def rate_limit_key(self, scope, identifier):
        return f"rate-limit:{scope}:{identifier}"


@pytest.fixture(autouse=True)
def passthrough_rate_limiter(monkeypatch):
    cache = FakeRateLimitCache()
    monkeypatch.setattr(main, "get_rate_limit_cache", lambda: cache)
    return cache


def test_gateway_health_reports_emotion_service(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        assert method == "GET"
        if "8002" in url:
            return _json_response(
                200,
                {
                    "status": "ok",
                    "database": "emotion_music_ai",
                },
            )
        if "8004" in url:
            return _json_response(
                200,
                {
                    "status": "ok",
                    "service": "recommendation-service",
                    "provider": "jamendo",
                    "jamendo_configured": True,
                },
            )

        return _json_response(
            200,
            {
                "status": "ok",
                "model_available": True,
                "model": "fake-model.hdf5",
            },
        )

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api-gateway"
    assert body["emotion_api"]["model"] == "fake-model.hdf5"
    assert body["auth_service"]["database"] == "emotion_music_ai"
    assert body["recommendation_service"]["provider"] == "jamendo"
    assert body["rate_limiter"]["available"] is True


def test_gateway_health_degrades_when_emotion_service_is_unavailable(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["emotion_api"]["status"] == "unavailable"


def test_gateway_forwards_auth_signup(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        assert method == "POST"
        assert url.endswith("/auth/signup")
        assert headers["content-type"] == "application/json"
        assert b"user@example.com" in content
        return _json_response(
            201,
            {
                "access_token": "token",
                "token_type": "bearer",
                "user": {"id": "1", "email": "user@example.com"},
            },
        )

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/auth/signup",
        json={"email": "user@example.com", "password": "good-password"},
    )

    assert response.status_code == 201
    assert response.json()["token_type"] == "bearer"


def test_gateway_forwards_auth_bearer_header(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        assert method == "GET"
        assert url.endswith("/auth/me")
        assert headers["authorization"] == "Bearer token"
        return _json_response(200, {"user": {"id": "1", "email": "user@example.com"}})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.get("/api/auth/me", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "user@example.com"


def test_gateway_forwards_recommendation_request(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            assert method == "GET"
            assert headers["authorization"] == "Bearer token"
            return _auth_me_response()

        assert method == "POST"
        assert url.endswith("/recommendation/from-emotion")
        assert headers["x-user-id"] == "auth-user"
        assert b"Happy" in content
        assert b"auth-user" in content
        return _json_response(200, {"emotion": "Happy", "tracks": []})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/recommendation/from-emotion",
        json={"emotion": "Happy"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.json()["emotion"] == "Happy"
    assert response.headers["x-ratelimit-limit"] == "20"
    assert response.headers["x-ratelimit-remaining"] == "19"


def test_gateway_rejects_recommendation_without_bearer_token(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        raise AssertionError("Unauthenticated recommendation should not be proxied.")

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/recommendation/from-emotion",
        json={"emotion": "Happy"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token."


def test_gateway_overwrites_spoofed_recommendation_user_id(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        body = content.decode("utf-8")
        assert '"user_id": "auth-user"' in body
        assert "spoofed-user" not in body
        return _json_response(200, {"emotion": "Happy", "tracks": []})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/recommendation/from-emotion",
        json={"emotion": "Happy", "user_id": "spoofed-user"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200


def test_gateway_injects_user_id_for_current_emotion_lookup(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        assert method == "GET"
        assert url.endswith("/recommendation/current-emotion?user_id=auth-user")
        assert headers["x-user-id"] == "auth-user"
        assert "spoofed-user" not in url
        return _json_response(200, {"emotion": "Happy"})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.get(
        "/api/recommendation/current-emotion?user_id=spoofed-user",
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.json() == {"emotion": "Happy"}


def test_gateway_forwards_playback_event_with_trusted_user_id(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        assert method == "POST"
        assert url.endswith("/recommendation/playback/event")
        assert headers["x-user-id"] == "auth-user"
        body = content.decode("utf-8")
        assert '"user_id": "auth-user"' in body
        assert "spoofed-user" not in body
        assert "track-123" in body
        return _json_response(200, {"status": "ok"})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/playback/event",
        json={
            "event_type": "started",
            "track_id": "track-123",
            "user_id": "spoofed-user",
            "emotion": "Happy",
            "provider": "jamendo",
        },
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_gateway_rejects_playback_event_without_bearer_token(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        raise AssertionError("Unauthenticated playback should not be proxied.")

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/playback/event",
        json={"event_type": "started", "track_id": "track-123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token."


def test_gateway_rate_limits_recommendation_requests(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        return _json_response(200, {"emotion": "Happy", "tracks": []})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    for _index in range(20):
        response = client.post(
            "/api/recommendation/from-emotion",
            json={"emotion": "Happy"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 200

    response = client.post(
        "/api/recommendation/from-emotion",
        json={"emotion": "Happy"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Rate limit exceeded."
    assert response.json()["limit"] == 20
    assert response.headers["x-ratelimit-limit"] == "20"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.headers["retry-after"] == "60"


def test_gateway_rate_limit_response_is_browser_readable(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        return _json_response(200, {"emotion": "Happy", "tracks": []})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    for _index in range(20):
        response = client.post(
            "/api/recommendation/from-emotion",
            json={"emotion": "Happy"},
            headers={**AUTH_HEADER, "Origin": "http://127.0.0.1:5173"},
        )
        assert response.status_code == 200

    response = client.post(
        "/api/recommendation/from-emotion",
        json={"emotion": "Happy"},
        headers={**AUTH_HEADER, "Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "Retry-After" in response.headers["access-control-expose-headers"]


def test_gateway_rate_limiter_fails_open_when_redis_is_unavailable(monkeypatch):
    cache = FakeRateLimitCache(unavailable=True)

    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        return _json_response(200, {"emotion": "Happy", "tracks": []})

    monkeypatch.setattr(main, "get_rate_limit_cache", lambda: cache)
    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/recommendation/from-emotion",
        json={"emotion": "Happy"},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.headers["x-ratelimit-policy"] == "fail-open"


def test_gateway_health_degrades_when_rate_limiter_is_unavailable(monkeypatch):
    cache = FakeRateLimitCache(unavailable=True)

    async def fake_request_downstream(method, url, headers=None, content=None):
        return _json_response(200, {"status": "ok"})

    monkeypatch.setattr(main, "get_rate_limit_cache", lambda: cache)
    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["rate_limiter"]["available"] is False


def test_gateway_preserves_auth_unauthorized_response(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        return _json_response(401, {"detail": "Missing bearer token."})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token."


def test_gateway_forwards_emotion_metadata(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        assert method == "GET"
        assert url.endswith("/emotion/metadata")
        assert headers["x-user-id"] == "auth-user"
        return _json_response(200, {"labels": ["Happy"]})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.get("/api/emotion/metadata", headers=AUTH_HEADER)

    assert response.status_code == 200
    assert response.json() == {"labels": ["Happy"]}


def test_gateway_forwards_emotion_detection_upload(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        assert method == "POST"
        assert url.endswith("/emotion/detect")
        assert headers["content-type"].startswith("multipart/form-data")
        assert headers["x-user-id"] == "auth-user"
        assert b"face.jpg" in content
        return _json_response(
            200,
            {
                "emotion": "Happy",
                "confidence": 0.87,
                "face": {"x": 1, "y": 2, "width": 3, "height": 4},
            },
        )

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/emotion/detect",
        files={"file": ("face.jpg", b"fake image", "image/jpeg")},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 200
    assert response.json()["emotion"] == "Happy"


def test_gateway_preserves_emotion_error_response(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        return _json_response(422, {"detail": "No face was detected."})

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/emotion/detect",
        files={"file": ("blank.jpg", b"fake image", "image/jpeg")},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "No face was detected."


def test_gateway_returns_clear_emotion_timeout_error(monkeypatch):
    async def fake_request_downstream(method, url, headers=None, content=None):
        if url.endswith("/auth/me"):
            return _auth_me_response()

        raise httpx.ReadTimeout("")

    monkeypatch.setattr(main, "request_downstream", fake_request_downstream)
    client = TestClient(main.app)

    response = client.post(
        "/api/emotion/detect",
        files={"file": ("face.jpg", b"fake image", "image/jpeg")},
        headers=AUTH_HEADER,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Emotion API request failed: ReadTimeout"


def test_gateway_cors_allows_local_frontend_origin():
    client = TestClient(main.app)

    response = client.options(
        "/api/emotion/detect",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
