# Music Recommendation Platform

## Why

The current project can detect facial emotion from a local webcam, but the product goal is a full music recommendation system where a user logs in, detects emotion, receives Jamendo-backed track recommendations, and opens playable music links. This spec turns that goal into a phased implementation plan grounded in the existing Python/OpenCV project.

## What

Build the platform in stages, starting by stabilizing the existing emotion detector as a reusable backend capability, then adding an API, frontend, Jamendo-backed recommendation logic, persistence, eventing, cache, and deployment scaffolding.

Acceptance criteria for the complete goal:

- A user can open a web UI and log in.
- The app can capture or upload an image frame, detect the primary face emotion, and show emotion plus confidence.
- The system can convert emotion into recommendation intent and return playable Jamendo tracks.
- The user can open Jamendo audio and track pages from the web UI.
- Emotion and recommendation activity are persisted where needed and cached where useful.
- Services have clear ownership boundaries matching the draft: frontend, API gateway, auth, emotion, recommendation, cache, event bus, and database.
- Each phase can be verified before the next phase starts.

## Constraints

### Must

- Preserve the existing local webcam app while extracting reusable detection logic.
- Use the existing FER2013 mini-XCEPTION model at `models/fer2013_mini_XCEPTION.102-0.66.hdf5` unless a later model replacement is explicitly approved.
- Keep the emotion pipeline labels compatible with `utils/labels.py`.
- Add service boundaries incrementally; do not jump directly to Kubernetes/microservices before a working API and UI exist.
- Keep secrets out of source control; Jamendo client IDs, JWT secrets, database URLs, Redis URLs, and Kafka URLs must come from environment variables.
- Add explicit health checks and smoke tests for every backend service.
- Document setup commands as the architecture grows.

### Must Not

- Do not add account-linking OAuth unless a later provider explicitly requires it.
- Do not let React own recommendation ranking logic.
- Do not make the frontend responsible for recommendation ranking logic.
- Do not make Kafka mandatory for local emotion detection in the first API phase.
- Do not remove existing CLI flags from `app.py` unless replacement behavior is implemented and documented.

### Out of Scope

- Training a new emotion model.
- Real-time multi-user analytics dashboards.
- Mobile native apps.
- Production Kubernetes hardening before the local Docker Compose version is complete.
- Payment, subscriptions, or social sharing features.

## Current State

The repository started as a Python desktop/webcam emotion detection app. It opens a webcam, detects the primary face using OpenCV first and MediaPipe as a fallback, crops the face, runs the Keras emotion model, and overlays emotion/confidence on the frame.

- Relevant files: `app.py`
- Relevant files: `camera/webcam.py`
- Relevant files: `detection/face_detector.py`
- Relevant files: `detection/emotion_detector.py`
- Relevant files: `utils/preprocessing.py`
- Relevant files: `utils/labels.py`
- Relevant files: `models/fer2013_mini_XCEPTION.102-0.66.hdf5`
- Relevant files: `requirements.txt`
- Existing pattern: `app.py --check` verifies imports and model startup without opening the webcam.
- Existing pattern: detector classes are small wrappers with lazy dependency error messages.
- Existing gap: `config.py` is empty and can become the first central place for environment-backed configuration.

## Tasks

### T1: Stabilize The Existing Emotion Core
**What:** Add a minimal testable contract around face preprocessing and emotion prediction, document the current CLI behavior, and ensure `python app.py --check` remains the baseline smoke test. Add tests for label shape, preprocessing output shape/range, empty crop handling, and detector import behavior where practical.
**Files:** `app.py`, `detection/emotion_detector.py`, `utils/preprocessing.py`, `utils/labels.py`, `requirements.txt`, `README.md`, `tests/`
**Verify:** `python app.py --check`; `pytest`

Acceptance criteria:

- Existing webcam flow still launches with `python app.py`.
- `python app.py --check` loads OpenCV, the face detector, and the emotion model without opening the camera.
- Tests verify preprocessing returns the model-compatible normalized input shape, currently `(1, 64, 64, 1)`.
- A short README explains current setup, model file expectation, and CLI flags.

### T2: Extract An Emotion API Service
**What:** Add a FastAPI service that exposes the emotion detector through HTTP while reusing the existing detector/preprocessing code. Include endpoints for health, model metadata, image upload detection, and optionally a single webcam-frame debug route if useful locally.
**Files:** `services/emotion_api/`, `detection/`, `utils/`, `config.py`, `requirements.txt`, `README.md`, `tests/`
**Verify:** `uvicorn services.emotion_api.main:app --reload`; `pytest`; manual check: upload a face image to `POST /emotion/detect` and receive emotion, confidence, and face box.

Acceptance criteria:

- `GET /health` returns service status and model availability.
- `GET /emotion/metadata` returns labels and model name/path metadata without exposing secrets.
- `POST /emotion/detect` accepts an image and returns a JSON result like `{ "emotion": "Happy", "confidence": 0.87, "face": { ... } }`.
- If no face is detected, the API returns a clear 422-style response rather than a server error.
- The original `app.py` CLI still works.

### T3: Add Frontend Prototype For Detection
**What:** Create a React frontend that can open the camera, capture a frame, call the emotion API through a configurable API base URL, and display emotion/confidence with useful loading and error states.
**Files:** `frontend/`, `services/emotion_api/`, `.env.example`, `README.md`
**Verify:** run the frontend dev server; run the emotion API; manual check: browser camera permission appears, capture sends a frame, emotion result is displayed.

Acceptance criteria:

- The first screen is the usable detector interface, not a marketing page.
- UI shows camera preview, capture/detect control, current emotion, confidence, and API errors.
- Frontend API URL is environment-configurable.
- The UI is responsive on desktop and mobile viewport sizes.

### T4: Introduce API Gateway Boundary
**What:** Add a lightweight gateway that React calls for all backend routes. Route `/api/emotion/*` to the emotion API first, then leave extension points for auth and recommendations.
**Files:** `services/api_gateway/`, `frontend/`, `.env.example`, `README.md`, `tests/`
**Verify:** run gateway and emotion API; manual check: frontend calls `/api/emotion/detect` through gateway, not the emotion service directly.

Acceptance criteria:

- Gateway exposes `GET /api/health`.
- Gateway forwards emotion detection requests and preserves useful error responses.
- CORS policy allows the local frontend origin only through configuration.
- React only needs one backend base URL.

### T5: Add Auth Service And User Persistence
**What:** Add user signup/login, JWT issuance, password hashing, and a database-backed user model. Start with local PostgreSQL via Docker Compose or a clearly documented local database URL.
**Files:** `services/auth/`, `services/api_gateway/`, `database/`, `docker-compose.yml`, `.env.example`, `README.md`, `tests/`
**Verify:** `pytest`; manual check: create account, log in, call an authenticated route with `Authorization: Bearer <JWT>`.

Acceptance criteria:

- Users can sign up and log in with email/password.
- Passwords are hashed; plaintext passwords are never stored.
- Protected gateway routes reject missing/invalid JWTs.
- Database migrations or schema setup are repeatable from a clean checkout.

### T6: Add Jamendo Client Boundary
**What:** Implement Jamendo track lookup behind the recommendation service. Support environment-backed client ID configuration, search, track metadata normalization, health visibility, and clear upstream error messages.
**Files:** `services/recommendation/`, `services/api_gateway/`, `.env.example`, `README.md`, `tests/`
**Verify:** `pytest`; manual check: a configured Jamendo client ID can search tracks and return playable audio URLs.

Acceptance criteria:

- Jamendo uses environment-provided `JAMENDO_CLIENT_ID`.
- No user OAuth or Premium account is required for recommendations.
- Jamendo responses are normalized into a frontend-friendly track shape.
- Jamendo errors such as missing client ID or upstream failures return actionable API errors.

### T7: Add Recommendation Service
**What:** Convert detected emotion into recommendation intent and ranked Jamendo tracks. Start with deterministic mappings from emotion to search/ranking inputs, then add user preferences/listening history once persistence exists.
**Files:** `services/recommendation/`, `services/api_gateway/`, `database/`, `README.md`, `tests/`
**Verify:** `pytest`; manual check: detected emotion produces a list of recommended tracks with Jamendo IDs, titles, artists, artwork, licenses, and playable audio URLs.

Acceptance criteria:

- Each supported emotion maps to a documented music intent.
- Recommendations include enough metadata for the frontend to render and play tracks.
- The service avoids immediately repeating the same tracks for the same user where history is available.
- If Jamendo search fails, the API returns a clear failure state and the frontend handles it.

### T8: Add Redis Cache And Cooldowns
**What:** Add Redis for current emotion, recommendation cache, and cooldowns so repeated identical detections do not trigger excessive Jamendo calls.
**Files:** `services/recommendation/`, `services/emotion_api/`, `docker-compose.yml`, `.env.example`, `README.md`, `tests/`
**Verify:** `pytest`; manual check: repeated same-emotion detection within cooldown returns cached recommendations and does not call Jamendo again.

Acceptance criteria:

- Redis keys and TTLs are documented.
- Cache miss path still works when Redis is empty.
- Cache unavailable behavior is explicit: either fail gracefully or continue without cache based on service configuration.
- Cooldown prevents rapid duplicate recommendation generation per user/emotion.

### T9: Add Event Bus For Decoupled Workflows
**What:** Add Kafka-compatible event publishing and consuming for emotion events, recommendation events, playback events, and future analytics/history consumers. Keep synchronous API paths working for user-facing requests.
**Files:** `services/emotion_api/`, `services/recommendation/`, `services/events/`, `docker-compose.yml`, `.env.example`, `README.md`, `tests/`
**Verify:** run local broker stack; produce a test emotion event; confirm recommendation consumer handles it; `pytest`

Acceptance criteria:

- Event schemas are versioned and documented.
- Emotion service publishes `emotion.detected` events after successful detection.
- Recommendation service can consume emotion events and persist or cache recommendation results.
- Playback service publishes playback events for play/pause/skip actions.
- Services can start in local development with eventing disabled or unavailable if configured that way.

### T10: Complete Product UI
**What:** Expand React from detection prototype into the full app flow: login/signup, camera detection, current emotion, Jamendo recommendations, playable track links, and basic user profile/settings.
**Files:** `frontend/`, `services/api_gateway/`, `.env.example`, `README.md`, `tests/`
**Verify:** frontend tests; manual check: new user completes login, emotion detection, recommendation, and track opening from the browser.

Acceptance criteria:

- User can complete the happy path without manually calling backend endpoints.
- UI handles unauthenticated, no-face, no-recommendations, and Jamendo-unavailable states.
- Track actions open Jamendo audio URLs or track pages.
- Recommendations update after a new accepted emotion detection or cached response.

### T11: Add Local Orchestration And Developer Docs
**What:** Add Docker Compose profiles or scripts for running the gateway, auth, emotion, recommendation, frontend, database, Redis, and Kafka locally. Document environment setup and troubleshooting.
**Files:** `docker-compose.yml`, `.env.example`, `README.md`, `Makefile` or scripts, service Dockerfiles
**Verify:** start the documented local stack from a clean checkout; run health checks for all services.

Acceptance criteria:

- `.env.example` lists every required variable with safe placeholder values.
- One documented command starts the local stack.
- Each service has a health endpoint.
- README includes architecture diagram text, service responsibilities, setup, verification, and common failure modes.

### T12: Prepare Production Deployment Shape
**What:** Add production-facing configuration boundaries for containers, migrations, secrets, observability, and eventual Kubernetes deployment. This is a readiness phase after the local stack works.
**Files:** deployment manifests or `infra/`, service Dockerfiles, `README.md`, CI configuration
**Verify:** build all service images; run migrations against a staging-like database; smoke test deployed health endpoints.

Acceptance criteria:

- Containers build reproducibly.
- Runtime config is environment-based.
- Secrets are not committed.
- Logs include request IDs or correlation IDs across gateway and services.
- A deployment runbook explains order of operations and rollback basics.

## Validation

End-to-end validation after all phases:

- `python app.py --check`
- `pytest`
- Frontend test command selected by the chosen frontend stack.
- Backend service test commands selected by the chosen API stack.
- Docker Compose smoke test: start database, Redis, Kafka, backend services, gateway, and frontend from documented commands.
- Manual check: create a user, detect emotion from the camera, receive Jamendo recommendations, open a track, and confirm relevant activity is persisted/cached.
- Manual unhappy-path check: deny camera permission, submit a frame with no face, remove the Jamendo client ID, and stop the recommendation service; each case should produce a clear user-facing state and a non-500 backend response where possible.
