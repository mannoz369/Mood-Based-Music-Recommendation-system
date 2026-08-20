# Redis, Kafka, Dynamic Recommendations, And Mood Analytics

## Why

The current app can detect a user's mood and request Jamendo recommendations, but repeated requests can return routine songs, camera capture is not interval-driven, and there is no event pipeline for recommendation workflows or analytics. This plan adds Redis for fast operational state and Kafka for asynchronous mood, recommendation, playback, and analytics workflows without blocking the user-facing API.

## What

Implement the next platform increment in two phases.

Phase 1 adds Redis-backed rate limiting, cooldowns, recent-track memory, dynamic recommendation query generation, and interval-based camera capture.

Phase 2 adds Kafka event publishing and consuming for both recommendation and analytics services, plus a dedicated analytics service that tracks user mood history, recommendation history, and playback behavior.

Target architecture:

```text
React Frontend
  -> API Gateway
    -> Auth Service
    -> Emotion API
    -> Recommendation Service
    -> Analytics Service

Shared infrastructure:
  -> Redis for fast state, limits, cache, cooldowns, current mood, recent tracks
  -> Kafka or Redpanda for async events consumed by recommendation and analytics
  -> MongoDB for users and long-lived analytics records
```

## Constraints

### Must

- Keep the user-facing detection and recommendation path synchronous so the UI still receives immediate results.
- Use Redis for rate limiter counters, recommendation cache, cooldowns, current mood, and recent recommended/played track IDs.
- Use Kafka events for analytics and for asynchronous recommendation workflows.
- Kafka must publish events that the recommendation service can consume, not only analytics.
- Services must start with Redis or Kafka unavailable when configured for local fail-open behavior.
- Run Redis locally through Docker Compose, not as a direct host install.
- Continue using environment variables for secrets and infrastructure URLs.
- Preserve existing API gateway, emotion API, auth service, recommendation service, and frontend boundaries.
- Add focused tests around rate limits, dynamic query generation, Redis behavior, event publishing, and event consumption.

### Must Not

- Do not make React responsible for recommendation ranking or track filtering.
- Do not make Kafka mandatory for immediate user-facing recommendation responses.
- Do not store image frames in Kafka, Redis, or MongoDB by default.
- Do not commit Jamendo, MongoDB, Redis, Kafka, or JWT secrets.
- Do not remove the existing local webcam app behavior in `app.py`.

### Out of Scope

- Training or replacing the emotion model.
- Real-time analytics dashboards.
- Kubernetes production hardening.
- Paid music provider integrations or user OAuth with music services.
- Long-term raw image storage.

## Current State

The repo already has a small service-oriented FastAPI backend and a React frontend.

- Relevant files: `config.py`
- Relevant files: `.env.example`
- Relevant files: `requirements.txt`
- Relevant files: `services/api_gateway/main.py`
- Relevant files: `services/emotion_api/main.py`
- Relevant files: `services/emotion_api/detection_service.py`
- Relevant files: `services/recommendation/main.py`
- Relevant files: `services/recommendation/service.py`
- Relevant files: `services/recommendation/intents.py`
- Relevant files: `services/recommendation/cache.py`
- Relevant files: `services/recommendation/jamendo_client.py`
- Relevant files: `services/auth/main.py`
- Relevant files: `services/auth/service.py`
- Relevant files: `services/auth/repository.py`
- Relevant files: `frontend/src/App.jsx`
- Relevant files: `tests/test_recommendation_service.py`
- Relevant files: `tests/test_api_gateway.py`

Existing patterns to follow:

- `config.py` owns environment-backed settings through dataclasses and getter functions.
- FastAPI services expose `/health` endpoints and are proxied through `services/api_gateway/main.py`.
- Recommendation currently maps each FER2013 emotion to one static Jamendo search query in `services/recommendation/intents.py`.
- `services/recommendation/cache.py` already wraps Redis JSON/text access, but cooldown keys are written more than they are enforced.
- The frontend already captures a camera frame, calls `/api/emotion/detect`, then calls `/api/recommendation/from-emotion`.
- The frontend currently auto-captures once after sign-in; it does not yet support continuous interval mood tracking.

## Tasks

## Phase 1: Redis, Rate Limits, Dynamic Recommendations, And Interval Capture

### T0: Add Dockerized Redis For Local Phase 1 Development

**What:** Add a minimal `docker-compose.yml` Redis service before wiring Redis-dependent behavior into the gateway and recommendation flows. Redis should be run as a container, not installed directly on the developer machine.

Suggested service:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

Required behavior:

- `REDIS_URL=redis://127.0.0.1:6379/0` points services at the Dockerized Redis instance.
- Redis can be started independently with `docker compose up -d redis`.
- Services still fail open when Redis is stopped and `REDIS_FAIL_OPEN=true`.
- Later T13 should extend this same Compose file with MongoDB and Redpanda instead of replacing it.

**Files:** `docker-compose.yml`, `.env.example`, `README.md`

**Verify:** `docker compose up -d redis`; manual check: `docker compose exec redis redis-cli ping` returns `PONG`.

### T1: Expand Redis Into Shared Operational State

**What:** Extend the Redis wrapper so it can support JSON values, text values, atomic counters, TTL checks, cooldown reads, and bounded recent-track lists. Keep the wrapper fail-open for local development when `REDIS_URL` is not configured.

Redis responsibilities:

- Rate limiter counters with TTL.
- Current mood per user.
- Emotion cooldown per user and emotion.
- Recommendation response cache.
- Recent recommended track IDs.
- Recent played track IDs.

Suggested keys:

```text
rate-limit:{scope}:{identifier}
current-emotion:{user_id}
cooldown:{user_id}:{emotion}
recommendations:{user_id}:{emotion}:{limit}:{language}:{query_signature}
recent-recommended-tracks:{user_id}
recent-played-tracks:{user_id}
```

Suggested recent-track behavior:

```text
LPUSH recent-recommended-tracks:{user_id} <track_id>
LTRIM recent-recommended-tracks:{user_id} 0 49
EXPIRE recent-recommended-tracks:{user_id} 86400
```

**Files:** `services/recommendation/cache.py`, `config.py`, `.env.example`, `tests/test_recommendation_service.py`

**Verify:** `pytest tests/test_recommendation_service.py`

### T2: Add Redis-Backed Gateway Rate Limiting

**What:** Add API gateway middleware or route-level dependency that applies Redis-backed rate limits by user ID when available and by client IP for anonymous requests. Return `429` with clear JSON and rate-limit headers when a limit is exceeded.

Suggested limits:

```text
/api/auth/login: 5 requests per minute
/api/emotion/detect: 10 requests per minute per user or IP
/api/recommendation/from-emotion: 20 requests per minute per user or IP
fallback: 120 requests per minute per IP
```

If Redis is unavailable and fail-open is enabled, allow the request and expose degraded status in gateway health.

**Files:** `services/api_gateway/main.py`, `config.py`, `.env.example`, `tests/test_api_gateway.py`

**Verify:** `pytest tests/test_api_gateway.py`

### T3: Make Recommendation Requests User-Aware

**What:** Ensure recommendation requests use a stable authenticated user identity so Redis cache, cooldowns, and recent-track memory are per user. Resolve user ID at the gateway from the bearer token and inject/forward it to the recommendation service from trusted gateway code only. Client-provided `user_id` must not be trusted for normal app traffic.

Required behavior:

- Authenticated users get cache keys under their real user ID.
- Emotion detection, recommendation, playback, and analytics app routes require authentication in normal app mode.
- Anonymous or caller-supplied `user_id` is allowed only when an explicit local-development flag is enabled.
- Gateway strips or overwrites any client-supplied `user_id` before forwarding recommendation requests.
- Direct recommendation-service `user_id` input is treated as internal/dev-only and must not be publicly exposed in production.
- Frontend should not own recommendation ranking or Redis key decisions.
- Tests cover that a user cannot spoof another user's Redis identity by sending a different `user_id`.

**Files:** `services/api_gateway/main.py`, `services/recommendation/main.py`, `services/recommendation/service.py`, `frontend/src/App.jsx`, `tests/test_api_gateway.py`, `tests/test_recommendation_service.py`

**Verify:** `pytest tests/test_api_gateway.py tests/test_recommendation_service.py`

### T4: Add Dynamic Recommendation Query Generation

**What:** Replace fixed one-query-per-emotion behavior with a dynamic query builder. Keep the emotion intent stable, but vary Jamendo search terms and ranking inputs on each request unless a cache hit is intentionally returned.

Dynamic inputs:

- Emotion intent.
- Language preference.
- User ID.
- Recent recommended track IDs.
- Recent played track IDs.
- Request seed or timestamp bucket.
- Mood profile variants such as genre, energy, instrument, tempo, and vibe.

Example variants for `Happy`:

```text
dance pop rock upbeat feel good
funk bright groove upbeat
indie pop sunny energetic
electronic dance cheerful
pop summer high energy
```

The recommendation response should include enough debug metadata to verify variation without exposing secrets:

```json
{
  "query": "funk bright groove upbeat",
  "query_seed": "2026-08-18T10:15:user-123:Happy",
  "dynamic_profile": {
    "intent": "amplify",
    "energy": "medium-high",
    "variant": "funk-groove"
  }
}
```

**Files:** `services/recommendation/intents.py`, `services/recommendation/service.py`, `services/recommendation/jamendo_client.py`, `tests/test_recommendation_service.py`, `README.md`

**Verify:** `pytest tests/test_recommendation_service.py`

### T5: Exclude Recent Tracks And Update Redis Memory

**What:** Fetch more Jamendo tracks than the UI needs, filter out recent recommended and played track IDs from Redis, deduplicate the final list, and write returned tracks to recent recommendation memory. Later playback events will update recent played memory.

Required behavior:

- If the UI asks for 5 songs, request a larger candidate pool, such as 15.
- Filter `recent-recommended-tracks:{user_id}` and `recent-played-tracks:{user_id}`.
- If filtering removes too many tracks, return the best available non-duplicate candidates instead of an empty response.
- Cache should include the dynamic query signature so Redis does not force the same routine songs every time.

**Files:** `services/recommendation/service.py`, `services/recommendation/cache.py`, `tests/test_recommendation_service.py`

**Verify:** `pytest tests/test_recommendation_service.py`

### T6: Add Interval-Based Camera Auto Capture

**What:** Upgrade frontend auto-capture from one sign-in capture to user-controlled interval mood tracking. Add controls for enabling/disabling auto tracking, capture interval, confidence threshold, and whether songs should refresh only when mood changes.

Suggested controls:

```text
Auto mood tracking: on/off
Capture interval: 30s, 60s, 120s
Confidence threshold: 50%-90%
Refresh songs only when mood changes: on/off
```

Required behavior:

- No overlapping detection requests.
- Stop interval when camera stops, user logs out, or component unmounts.
- Respect rate limits and show a clear message on `429`.
- Continue current playback unless a meaningful mood change or cooldown expiry triggers a queue refresh.

**Files:** `frontend/src/App.jsx`, `frontend/src/styles.css`, `README.md`

**Verify:** `cd frontend` then `npm run build`; manual check: sign in, enable auto tracking, confirm repeated captures happen at the selected interval, and confirm logout stops camera and interval.

### T7: Add Playback Event Endpoint And Redis Played-Track Updates

**What:** Add an API route for playback events so the app can track started, paused, skipped, and ended tracks. For Phase 1, use the endpoint to update Redis recent played memory. Phase 2 will publish the same events to Kafka.

Suggested endpoint:

```text
POST /api/playback/event
```

Suggested body:

```json
{
  "event_type": "started",
  "track_id": "123",
  "emotion": "Happy",
  "provider": "jamendo"
}
```

Allowed event types:

```text
started
paused
skipped
ended
```

**Files:** `services/api_gateway/main.py`, `services/recommendation/main.py`, `services/recommendation/service.py`, `frontend/src/App.jsx`, `tests/test_api_gateway.py`, `tests/test_recommendation_service.py`

**Verify:** `pytest tests/test_api_gateway.py tests/test_recommendation_service.py`; manual check: play and skip tracks, then confirm Redis receives recent played track IDs.

## Phase 2: Kafka Recommendation Workflows And Analytics

### T8: Add Shared Kafka Event Module

**What:** Create a shared event package with versioned event envelopes, a Kafka producer, and a no-op producer for local development. Kafka should be optional for immediate API responses.

Initial topics:

```text
camera.capture.v1
emotion.detected.v1
recommendation.requested.v1
recommendation.generated.v1
recommendation.served.v1
playback.event.v1
```

Event envelope:

```json
{
  "event_id": "uuid",
  "event_type": "emotion.detected",
  "schema_version": 1,
  "occurred_at": "2026-08-18T10:15:00Z",
  "user_id": "user-123",
  "correlation_id": "request-123",
  "source_service": "emotion-api",
  "payload": {}
}
```

**Files:** `services/events/`, `config.py`, `.env.example`, `requirements.txt`, `tests/`

**Verify:** `pytest tests`

### T9: Publish Events From User-Facing Services

**What:** Publish Kafka events from existing services while keeping API responses synchronous.

Publish:

- `camera.capture.v1` when the frontend/gateway receives a capture attempt.
- `emotion.detected.v1` after successful emotion detection.
- `recommendation.requested.v1` when recommendations are requested.
- `recommendation.served.v1` after recommendations are returned to the user.
- `playback.event.v1` when playback starts, pauses, skips, or ends.

Required behavior:

- Kafka publish failure should not break detection or recommendation when fail-open is enabled.
- Events must include `user_id`, `emotion`, confidence where relevant, language, track IDs, cache hit/miss, query, and dynamic profile metadata.

**Files:** `services/api_gateway/main.py`, `services/emotion_api/main.py`, `services/recommendation/main.py`, `services/recommendation/service.py`, `frontend/src/App.jsx`, `tests/`

**Verify:** `pytest tests`; manual check: trigger detection and recommendation, then confirm events are produced when Kafka is enabled.

### T10: Add Recommendation Service Kafka Consumer

**What:** Add a consumer inside or alongside the recommendation service so Kafka events can drive asynchronous recommendation preparation. This lets the system precompute or warm recommendations when mood changes are detected, even before the user explicitly refreshes songs.

Consume:

```text
emotion.detected.v1
playback.event.v1
```

Recommendation consumer responsibilities:

- On `emotion.detected.v1`, check Redis cooldown and current mood.
- If mood changed or cooldown expired, build a dynamic recommendation query.
- Fetch candidate Jamendo tracks when configured to precompute.
- Store generated recommendation results in Redis under a query signature.
- Publish `recommendation.generated.v1`.
- On `playback.event.v1`, update recent played track memory and influence future filtering.

Important distinction:

- Synchronous API path still returns recommendations immediately.
- Kafka path prepares, warms, updates, and improves recommendation state asynchronously.
- Analytics is not the only Kafka consumer; recommendation also consumes mood and playback events.

**Files:** `services/recommendation/consumer.py`, `services/recommendation/service.py`, `services/events/`, `config.py`, `.env.example`, `tests/test_recommendation_service.py`

**Verify:** `pytest tests/test_recommendation_service.py`; manual check: produce a sample `emotion.detected.v1` event and confirm Redis receives a prepared recommendation payload.

### T11: Add Analytics Service Kafka Consumer

**What:** Create `services/analytics/` to consume Kafka events and store long-lived analytics records in MongoDB.

Consume:

```text
camera.capture.v1
emotion.detected.v1
recommendation.requested.v1
recommendation.generated.v1
recommendation.served.v1
playback.event.v1
```

Collections:

```text
analytics_events
user_mood_timeline
user_recommendation_history
user_playback_history
```

Analytics responsibilities:

- Store raw normalized event records.
- Store user mood timeline with emotion, confidence, and timestamps.
- Store recommendation history with query, dynamic profile, cache status, and track IDs.
- Store playback history with started, skipped, paused, and ended actions.
- Support future mood transition and recommendation effectiveness reports.

**Files:** `services/analytics/`, `services/events/`, `config.py`, `.env.example`, `tests/`

**Verify:** `pytest tests`; manual check: run analytics consumer, produce sample events, and confirm MongoDB documents are written.

### T12: Add Analytics API And Gateway Routes

**What:** Expose authenticated analytics read APIs and proxy them through the gateway.

Suggested analytics endpoints:

```text
GET /analytics/me/moods
GET /analytics/me/recommendations
GET /analytics/me/playback
GET /analytics/me/summary
```

Gateway routes:

```text
/api/analytics/*
```

Required behavior:

- A user can fetch only their own analytics.
- Gateway health includes analytics service status.
- Missing analytics service should degrade gateway health without breaking emotion detection or recommendations.

**Files:** `services/analytics/main.py`, `services/api_gateway/main.py`, `config.py`, `.env.example`, `tests/test_api_gateway.py`

**Verify:** `pytest tests/test_api_gateway.py`; manual check: logged-in user can fetch their mood and playback history.

### T13: Extend Local Infrastructure Orchestration

**What:** Extend the Phase 1 Docker Compose file with MongoDB and Kafka-compatible eventing. Redis should already exist in Compose from T0. Prefer Redpanda for simpler local Kafka-compatible development unless standard Kafka is specifically required.

Start with infra-only Compose:

```text
mongodb
redis
redpanda
```

Then document how to run app services locally against that infrastructure.

**Files:** `docker-compose.yml`, `.env.example`, `README.md`

**Verify:** `docker compose up -d redis mongodb redpanda`; manual check: Redis ping succeeds, MongoDB ping succeeds through auth/analytics health, and Kafka topics can be created or auto-created.

### T14: Production Network Exposure And Deployment Hardening

**What:** Before preparing the repo for a production environment, lock down service exposure so only the API Gateway is public. Internal service-to-service HTTP calls should remain private to the server or container network.

Required behavior:

- Expose only the API Gateway publicly, such as `8001` behind a reverse proxy or load balancer.
- Do not publicly expose Emotion API `8000`, Auth Service `8002`, Recommendation Service `8004`, Redis `6379`, RedisInsight `5540`, MongoDB, or Redpanda/Kafka ports.
- In Docker Compose or production container definitions, use `ports` only for the gateway and use internal networking or `expose` for backend services.
- Configure firewall/security-group rules so external traffic cannot reach internal service ports.
- Configure reverse proxy routes so `/api/*` reaches the gateway only, not individual backend services.
- Ensure service logs do not print bearer tokens, secrets, raw Redis URLs with credentials, MongoDB credentials, Jamendo keys, or full request bodies containing sensitive data.
- Keep RedisInsight disabled, removed, or network-restricted in production.
- Document how to verify from outside the host that only the gateway is reachable.

Suggested production-style Compose shape:

```yaml
services:
  api_gateway:
    ports:
      - "8001:8001"

  emotion_api:
    expose:
      - "8000"

  auth:
    expose:
      - "8002"

  recommendation:
    expose:
      - "8004"

  redis:
    expose:
      - "6379"
```

**Files:** `docker-compose.yml`, production Compose/deployment files if added, `README.md`, `.env.example`

**Verify:** From outside the host, `GET /api/health` through the public gateway succeeds, while direct requests to `8000`, `8002`, `8004`, `6379`, and `5540` fail or time out.

## Validation

Run the existing backend checks:

```powershell
pytest
python app.py --check
```

Run frontend build:

```powershell
cd frontend
npm run build
```

Service smoke checks:

```text
GET /api/health
GET /health on each backend service
GET /api/recommendation/intents
POST /api/emotion/detect
POST /api/recommendation/from-emotion
POST /api/playback/event
GET /api/analytics/me/summary
```

Redis verification:

- Rate limiter returns `429` after configured limits.
- `current-emotion:{user_id}` is written after mood detection.
- `cooldown:{user_id}:{emotion}` prevents excessive same-emotion refreshes.
- Recommendation cache keys include a dynamic query signature.
- `recent-recommended-tracks:{user_id}` is updated after recommendations are served.
- `recent-played-tracks:{user_id}` is updated after playback events.
- Repeated recommendation requests avoid recent track IDs when enough alternatives exist.

Kafka verification:

- Topics exist for camera, emotion, recommendation, and playback events.
- Emotion API or gateway publishes `emotion.detected.v1`.
- Recommendation service consumes `emotion.detected.v1` and can warm Redis recommendations.
- Recommendation service consumes `playback.event.v1` and updates recent played memory.
- Analytics service consumes all relevant topics and stores MongoDB records.
- Detection and recommendation still work when Kafka is disabled in local fail-open mode.

Frontend verification:

- User can sign up or log in.
- User can start camera manually.
- User can enable auto mood tracking.
- Camera captures at the selected interval.
- No overlapping detection requests happen.
- Meaningful mood changes trigger fresh recommendations.
- Songs vary across repeated requests because dynamic query generation and recent-track filtering are active.
- Playback started, skipped, paused, and ended events are sent.
- Logout stops the camera stream, interval timer, and playback.

End-to-end success state:

A signed-in user enables auto mood tracking, the camera captures periodically, detected mood updates Redis current state, Redis rate limits and cooldowns protect the backend, recommendation requests produce varied songs while avoiding recent tracks, Kafka sends mood and playback events to both recommendation and analytics consumers, and analytics stores user mood and playback history without blocking the user experience.
