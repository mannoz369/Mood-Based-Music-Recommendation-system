# Emotion Music AI

Emotion Music AI currently runs a local webcam emotion detector. It opens a camera with OpenCV, detects the primary face, preprocesses that face into the FER2013 model input format, predicts an emotion with the bundled mini-XCEPTION model, and overlays the emotion plus confidence on the video frame.

This is the first stabilized core for the larger music recommendation platform described in `music-recommendation-platform-spec.md`.

## Requirements

- Python 3.12
- Docker Desktop, for local Redis and Kafka
- A working webcam for the live app
- The emotion model at `models/fer2013_mini_XCEPTION.102-0.66.hdf5`

Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS or Linux, use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`.

## Local Infrastructure

Redis is used for recommendation cache state, cooldowns, rate-limit counters, current mood, and recent track memory. Kafka is used for asynchronous emotion, recommendation, and playback events. Run both through Docker Compose instead of installing them directly on your machine:

```powershell
docker compose up -d redis
docker compose --profile local-mongo --profile local-kafka --profile tools up -d mongodb redpanda redisinsight kafka-ui
```

Verify Redis is ready:

```powershell
docker compose ps redis
docker compose exec redis redis-cli ping
```

Expected result: `redis-cli ping` returns `PONG`.

Verify Kafka is ready:

```powershell
docker compose ps redpanda
docker compose exec redpanda rpk topic list
```

Expected result: the topic list command exits successfully. It may print no topics until the app publishes its first event.

Open RedisInsight at:

```text
http://127.0.0.1:5540
```

When adding the database in RedisInsight, use:

- Host: `redis`
- Port: `6379`
- Username: leave blank
- Password: leave blank

The default local `.env` values should point at Dockerized Redis and Kafka:

```env
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_NAMESPACE=emotion-music-ai
REDIS_FAIL_OPEN=true
KAFKA_ENABLED=true
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092
```

With `REDIS_FAIL_OPEN=true` and `KAFKA_FAIL_OPEN=true`, backend services can still start while Redis or Kafka is stopped, but Redis-backed behavior and async event behavior will be degraded.

All local infrastructure ports are bound to `127.0.0.1` in Compose so Redis, MongoDB, RedisInsight, and Redpanda are not exposed publicly by accident.

## Run The App

Start the webcam emotion overlay:

```powershell
python app.py
```

The app accepts these CLI flags:

- `--camera-index`: OpenCV camera index to open. Defaults to `0`.
- `--width`: requested webcam capture width. Defaults to `1280`.
- `--height`: requested webcam capture height. Defaults to `720`.
- `--check`: load OpenCV, the face detector, and the emotion model, then exit without opening the camera.

Example:

```powershell
python app.py --camera-index 1 --width 640 --height 480
```

Press `q` in the video window to quit.

## Smoke Test

Use the startup check before changing detection code:

```powershell
python app.py --check
```

Expected result: the command prints the OpenCV version, selected face detector backend, and bundled model filename without opening the camera.

## Emotion API

Task 2 adds a FastAPI service around the same detector code used by `app.py`.

Start the API:

```powershell
uvicorn services.emotion_api.main:app --reload
```

Useful endpoints:

- `GET /health`: service health, model availability, model name, and face detector backend.
- `GET /emotion/metadata`: configured emotion labels, model metadata, and face detector backend.
- `POST /emotion/detect`: multipart image upload under the `file` field. Returns `emotion`, `confidence`, and `face` box coordinates for the primary detected face.

Example upload:

```powershell
curl.exe -F "file=@face.jpg" http://127.0.0.1:8000/emotion/detect
```

The API returns `422` when no face is detected, `400` for unreadable images, `413` for oversized uploads, and `415` for non-image uploads.

Environment variables:

- `EMOTION_MODEL_PATH`: model file path. Defaults to `models/fer2013_mini_XCEPTION.102-0.66.hdf5`.
- `FACE_MIN_DETECTION_CONFIDENCE`: face detector confidence threshold. Defaults to `0.6`.
- `EMOTION_API_MAX_UPLOAD_BYTES`: upload limit in bytes. Defaults to `5242880`.
- `EMOTION_API_SERVICE_NAME`: service name returned by health checks. Defaults to `emotion-api`.
- `EMOTION_API_CORS_ORIGINS`: comma-separated browser origins allowed to call the API. Defaults to `http://localhost:5173,http://127.0.0.1:5173`.

## Frontend Prototype

Task 3 adds a React camera interface in `frontend/`.

Install frontend dependencies:

```powershell
cd frontend
npm install
```

Start the emotion API in one terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.emotion_api.main:app --reload
```

Start the API gateway in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.api_gateway.main:app --host 127.0.0.1 --port 8001 --reload
```

Start the frontend in a third terminal:

```powershell
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`, sign up or log in, start the camera, then capture a frame. The frontend posts the captured image to `POST /api/emotion/detect` through the gateway and displays the returned emotion, confidence, and face box.

The Preferences panel includes auto mood tracking controls:

- Auto mood tracking on/off.
- Capture interval: `30s`, `60s`, or `120s`.
- Confidence threshold from `50%` to `90%`.
- Refresh songs only when mood changes.

When auto tracking is enabled, the app avoids overlapping detection requests. Stopping the camera or logging out stops the interval. Low-confidence captures update the visible mood result but do not refresh the queue, and same-mood captures keep the current playback when mood-change-only refresh is enabled.

Frontend environment variable:

- `VITE_API_BASE_URL`: API gateway base URL. Defaults to `http://127.0.0.1:8001`.

## API Gateway

Task 4 adds a lightweight gateway in `services/api_gateway/`. The frontend calls this gateway for backend routes, and the gateway forwards emotion requests to the emotion API.

Start the gateway:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.api_gateway.main:app --host 127.0.0.1 --port 8001 --reload
```

Gateway endpoints:

- `GET /api/health`: gateway status plus downstream emotion API health.
- `GET /api/emotion/metadata`: forwarded to the emotion API metadata route.
- `POST /api/emotion/detect`: forwarded to the emotion API detection route.
- `POST /api/auth/signup`: forwarded to the auth service signup route.
- `POST /api/auth/login`: forwarded to the auth service login route.
- `GET /api/auth/me`: forwarded to the protected auth service profile route.
- `GET /api/recommendation/intents`: documented emotion-to-music intents.
- `POST /api/recommendation/from-emotion`: returns Jamendo tracks for an emotion.

Gateway environment variables:

- `API_GATEWAY_SERVICE_NAME`: service name returned by health checks. Defaults to `api-gateway`.
- `EMOTION_API_BASE_URL`: downstream emotion API base URL. Defaults to `http://127.0.0.1:8000`.
- `AUTH_SERVICE_BASE_URL`: downstream auth service base URL. Defaults to `http://127.0.0.1:8002`.
- `RECOMMENDATION_SERVICE_BASE_URL`: downstream recommendation service base URL. Defaults to `http://127.0.0.1:8004`.
- `API_GATEWAY_REQUEST_TIMEOUT_SECONDS`: downstream request timeout. Defaults to `60`.
- `API_GATEWAY_CORS_ORIGINS`: comma-separated browser origins allowed to call the gateway. Defaults to `http://localhost:5173,http://127.0.0.1:5173`.

## Auth Service

Task 5 adds an email/password auth service in `services/auth/`, backed by MongoDB Atlas through `MONGODB_URI`.

Create a MongoDB Atlas cluster, then set these environment variables before starting the auth service:

```powershell
$env:MONGODB_URI="mongodb+srv://<username>:<password>@<cluster-host>/?retryWrites=true&w=majority"
$env:MONGODB_DATABASE="emotion_music_ai"
$env:JWT_SECRET="<long-random-secret>"
```

You can also put those same values in a project-local `.env` file. The backend loads `D:\emotion-music-ai\.env` automatically at startup.

Start the auth service:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.auth.main:app --host 127.0.0.1 --port 8002 --reload
```

Auth endpoints:

- `GET /health`: reports MongoDB Atlas connectivity and index setup.
- `POST /auth/signup`: creates a user and returns a bearer token.
- `POST /auth/login`: validates credentials and returns a bearer token.
- `GET /auth/me`: protected route; requires `Authorization: Bearer <token>`.

Gateway auth examples:

```powershell
curl.exe -X POST http://127.0.0.1:8001/api/auth/signup -H "Content-Type: application/json" -d "{\"email\":\"you@example.com\",\"password\":\"good-password\"}"
curl.exe -X POST http://127.0.0.1:8001/api/auth/login -H "Content-Type: application/json" -d "{\"email\":\"you@example.com\",\"password\":\"good-password\"}"
curl.exe http://127.0.0.1:8001/api/auth/me -H "Authorization: Bearer <token>"
```

Passwords are stored as salted PBKDF2 hashes. Plaintext passwords and MongoDB Atlas credentials are never committed.

The frontend includes an account panel that calls `POST /api/auth/signup`, `POST /api/auth/login`, and `GET /api/auth/me` through the gateway. The bearer token is stored in browser `localStorage` for local development.

## Recommendation Service

Task 7 adds a recommendation service in `services/recommendation/`. It maps each supported FER2013 emotion to a documented music intent and Jamendo search query, then asks Jamendo for streamable track metadata.

Create a Jamendo developer application at `https://devportal.jamendo.com/`, copy its client ID, and add it to `.env`:

```env
JAMENDO_CLIENT_ID=your-jamendo-client-id
JAMENDO_API_BASE_URL=https://api.jamendo.com/v3.0
```

Emotion intents:

- `Angry`: de-escalate with calm focus tracks.
- `Disgust`: reset with bright, clean tracks.
- `Fear`: reassure with soothing ambient tracks.
- `Happy`: amplify with upbeat tracks.
- `Sad`: comfort with warm mellow tracks.
- `Surprise`: channel into discovery tracks.
- `Neutral`: focus with unobtrusive tracks.

Start the recommendation service:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.recommendation.main:app --host 127.0.0.1 --port 8004 --reload
```

For Redis-backed recommendation state and Kafka eventing, start Dockerized Redis and Kafka before the recommendation service:

```powershell
docker compose up -d redis kafka
```

Recommendation endpoints do not require OAuth, Premium, or an external user account connection:

```powershell
curl.exe http://127.0.0.1:8001/api/recommendation/intents
curl.exe -X POST http://127.0.0.1:8001/api/recommendation/from-emotion -H "Content-Type: application/json" -d "{\"emotion\":\"Happy\",\"limit\":5}"
```

PowerShell object-body example:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/recommendation/from-emotion" -Method Post -ContentType "application/json" -Body (@{ emotion = "Happy"; limit = 5 } | ConvertTo-Json)
```

You can filter recommendations by lyrics language using Jamendo's `lang` filter. The frontend stores the selected preference in browser `localStorage` and sends it with each recommendation request. Supported UI choices include `hi` Hindi, `te` Telugu, `ta` Tamil, `kn` Kannada, `ml` Malayalam, `bn` Bengali, `mr` Marathi, `pa` Punjabi, and `en` English.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/recommendation/from-emotion" -Method Post -ContentType "application/json" -Body (@{ emotion = "Happy"; limit = 5; language = "hi" } | ConvertTo-Json)
```

The response includes `emotion`, the chosen `intent`, `provider: "jamendo"`, and `tracks` with Jamendo IDs, names, artists, artwork, licenses, URLs, and streamable audio URLs.

Recommendation queries are dynamic. The service keeps each emotion's broad intent stable, then selects a profile variant from the user ID, emotion, language, recent-track memory, and a short UTC timestamp bucket. Responses include safe debug metadata:

```json
{
  "query": "funk bright groove upbeat",
  "query_seed": "2026-08-18T10:15Z:user-123:Happy:en::",
  "dynamic_profile": {
    "intent": "amplify",
    "energy": "medium-high",
    "variant": "funk-groove"
  }
}
```

For repeatable local checks, pass `request_seed` in `POST /recommendation/from-emotion` or `POST /api/recommendation/from-emotion`. The recommendation cache key includes the resulting query signature, so Redis can cache intentional repeats without pinning every future request to the same song search.

Playback events are sent through the gateway so Redis can remember recently played tracks:

```powershell
curl.exe -X POST http://127.0.0.1:8001/api/playback/event -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d "{\"event_type\":\"started\",\"track_id\":\"123\",\"emotion\":\"Happy\",\"provider\":\"jamendo\"}"
```

Allowed `event_type` values are `started`, `paused`, `skipped`, and `ended`. Phase 1 uses `started`, `skipped`, and `ended` to update:

```text
recent-played-tracks:{user_id}
```

The frontend sends these events best-effort when audio starts, pauses, skips, or ends. Future Kafka work will publish the same events asynchronously.

## Event Module

Phase 2 starts with a shared event package in `services/events/`. It defines versioned event envelopes, topic names, a no-op local producer, and a Kafka producer that is optional for synchronous API responses.

Initial event topics:

```text
camera.capture.v1
emotion.detected.v1
recommendation.requested.v1
recommendation.generated.v1
recommendation.served.v1
playback.event.v1
```

Kafka is disabled by default for local development:

```env
KAFKA_ENABLED=false
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092
KAFKA_CLIENT_ID=emotion-music-ai
KAFKA_FAIL_OPEN=true
```

When `KAFKA_ENABLED=false`, services can use the no-op producer and keep the user-facing API path synchronous. When Kafka is enabled but publishing fails and `KAFKA_FAIL_OPEN=true`, publish failures are reported by the producer without breaking the immediate API flow.

Start local Dockerized Redpanda/Kafka with:

```powershell
docker compose --profile local-kafka up -d redpanda
```

List Kafka topics with:

```powershell
docker compose exec redpanda rpk topic list
```

The user-facing services publish these Phase 2 events:

- `camera.capture.v1`: API gateway receives `POST /api/emotion/detect`. The payload contains capture metadata only, not image bytes.
- `emotion.detected.v1`: API gateway receives a successful emotion detection response.
- `recommendation.requested.v1`: recommendation service starts a mood-to-track request.
- `recommendation.served.v1`: recommendation service returns cached or freshly fetched tracks.
- `playback.event.v1`: recommendation service records playback start, pause, skip, or end.

The recommendation service can also consume Kafka events to warm Redis:

```powershell
.\.venv\Scripts\python.exe -m services.recommendation.consumer
```

It consumes `emotion.detected.v1` and `playback.event.v1`. On `emotion.detected.v1`, it checks current mood and same-emotion cooldown in Redis, precomputes recommendations when `RECOMMENDATION_PRECOMPUTE_ENABLED=true`, stores the generated recommendation payload in the normal recommendation cache, and publishes `recommendation.generated.v1`. On `playback.event.v1`, it updates `recent-played-tracks:{user_id}` without republishing the same playback event.

The analytics service can consume all app Kafka events and store raw plus derived records in MongoDB. It uses the same `MONGODB_URI` and `MONGODB_DATABASE` settings as the auth service:

```powershell
.\.venv\Scripts\python.exe -m services.analytics.consumer
```

It subscribes to `camera.capture.v1`, `emotion.detected.v1`, `recommendation.requested.v1`, `recommendation.generated.v1`, `recommendation.served.v1`, and `playback.event.v1`. It writes every event to `analytics_events`, mood events to `user_mood_timeline`, recommendation events to `user_recommendation_history`, and playback events to `user_playback_history`.

Start the analytics read API on port `8005`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn services.analytics.main:app --host 127.0.0.1 --port 8005 --reload
```

Authenticated users can read their own analytics through the gateway:

```text
GET /api/analytics/me/moods
GET /api/analytics/me/recommendations
GET /api/analytics/me/playback
GET /api/analytics/me/summary
```

Redis-related recommendation environment variables:

- `REDIS_URL`: Redis connection URL. Defaults locally to `redis://127.0.0.1:6379/0`.
- `REDIS_NAMESPACE`: key prefix for this app's Redis data. Defaults to `emotion-music-ai`.
- `REDIS_FAIL_OPEN`: allows services to continue when Redis is unavailable. Defaults to `true`.
- `RECOMMENDATION_CACHE_TTL_SECONDS`: recommendation response cache TTL. Defaults to `600`.
- `RECOMMENDATION_COOLDOWN_SECONDS`: current mood and emotion cooldown TTL. Defaults to `60`.
- `RECOMMENDATION_RECENT_TRACK_LIMIT`: max recent track IDs to keep per list. Defaults to `50`.
- `RECOMMENDATION_RECENT_TRACK_TTL_SECONDS`: recent track list TTL. Defaults to `86400`.

## EC2 Deployment Beside Airbnb-Replica

The `Airbnb-Replica` EC2 deployment already runs Redpanda/Kafka on its Docker network as service name `kafka` with broker address `kafka:29092`. Use that broker instead of starting another Kafka container for this app.

Production-style Compose files:

```text
docker-compose.prod.yml
docker-compose.ec2.yml
```

`docker-compose.prod.yml` runs this app's containers and only binds the API Gateway and frontend to `127.0.0.1` for host Nginx. Internal services use `expose`, not public `ports`.

`docker-compose.ec2.yml` joins the existing `airbnb-replica_default` Docker network and sets:

```env
KAFKA_ENABLED=true
KAFKA_BOOTSTRAP_SERVERS=kafka:29092
```

Prepare `.env` on EC2:

```bash
cp .env.example .env
nano .env
```

Required production values:

```env
MONGODB_URI=<your MongoDB Atlas URI>
MONGODB_DATABASE=emotion_music_ai
JWT_SECRET=<long random secret>
JAMENDO_CLIENT_ID=<your Jamendo client id>
REDIS_URL=redis://redis:6379/0
KAFKA_ENABLED=true
KAFKA_BOOTSTRAP_SERVERS=kafka:29092
API_GATEWAY_ALLOW_ANONYMOUS_APP_ROUTES=false
```

Build and start on the same EC2 instance:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.ec2.yml up --build -d
```

If the first build fails with `no space left on device`, clean the failed Docker build cache and retry. The production Compose uses a slim shared backend image for non-ML services and a separate full image only for `emotion_api`, but failed partial layers can still occupy disk:

```bash
docker builder prune -af
docker image prune -af
docker system df
docker compose -f docker-compose.prod.yml -f docker-compose.ec2.yml up --build -d
```

Install the Nginx reverse proxy route:

```bash
sudo cp deploy/nginx/emotion-music-ai.conf /etc/nginx/sites-available/emotion-music-ai.conf
sudo ln -sf /etc/nginx/sites-available/emotion-music-ai.conf /etc/nginx/sites-enabled/emotion-music-ai.conf
sudo nginx -t
sudo systemctl reload nginx
```

Public traffic should reach Nginx on `80` or `443`. Nginx proxies `/api/*` to `127.0.0.1:8001` and the React app to `127.0.0.1:5173`.

Verify on EC2:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.ec2.yml ps
curl http://127.0.0.1:8001/api/health
curl http://127.0.0.1:5173
docker exec airbnb-replica-kafka rpk topic list
```

Verify from your laptop:

```bash
curl http://<ec2-public-ip>/api/health
```

These direct ports should fail from outside the EC2 security group:

```text
8000 emotion api
8002 auth service
8004 recommendation service
8005 analytics service
6379 redis
5540 redisinsight
9092 kafka/redpanda
27017 mongodb
```

AWS security group should allow only SSH from your IP and public HTTP/HTTPS:

```text
22 from your IP
80 from 0.0.0.0/0
443 from 0.0.0.0/0
```

## Tests

Run the focused core test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The tests cover:

- Emotion label shape and order.
- Face preprocessing shape, dtype, and normalized value range.
- Empty face crop handling.
- Emotion detector prediction behavior with a fake model.
- Practical detector/app import behavior without opening the webcam.
