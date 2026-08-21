import hashlib
import json
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from config import get_api_gateway_settings, get_event_settings
from services.events import EventEnvelope, create_event_producer
from services.recommendation.cache import RecommendationCache


app = FastAPI(
    title="Emotion Music API Gateway",
    version="0.1.0",
    description="Frontend-facing gateway for emotion, auth, and recommendation APIs.",
)

settings = get_api_gateway_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-RateLimit-Policy",
    ],
)


@lru_cache(maxsize=1)
def get_rate_limit_cache():
    gateway_settings = get_api_gateway_settings()
    return RecommendationCache(
        gateway_settings.redis_url,
        namespace=gateway_settings.redis_namespace,
        fail_open=gateway_settings.redis_fail_open,
    )


@lru_cache(maxsize=1)
def get_event_producer():
    return create_event_producer(get_event_settings())


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    rate_limit = _rate_limit_for_request(request)

    if not rate_limit:
        return await call_next(request)

    gateway_settings = get_api_gateway_settings()
    scope, limit = rate_limit
    identifier_scope, identifier = _rate_limit_identifier(request)
    cache = get_rate_limit_cache()
    key = cache.rate_limit_key(scope, f"{identifier_scope}:{identifier}")
    count = await cache.increment_counter(
        key,
        ttl_seconds=gateway_settings.rate_limit_window_seconds,
    )

    if count is None:
        if gateway_settings.redis_fail_open:
            response = await call_next(request)
            response.headers["X-RateLimit-Policy"] = "fail-open"
            return response

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Rate limiter is unavailable."},
            headers=_cors_headers_for_request(request),
        )

    reset_seconds = await cache.ttl(key)

    if reset_seconds is None or reset_seconds < 0:
        reset_seconds = gateway_settings.rate_limit_window_seconds

    remaining = max(limit - count, 0)
    headers = _rate_limit_headers(limit, remaining, reset_seconds)

    if count > limit:
        headers["Retry-After"] = str(reset_seconds)
        headers.update(_cors_headers_for_request(request))
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Rate limit exceeded.",
                "limit": limit,
                "window_seconds": gateway_settings.rate_limit_window_seconds,
                "retry_after_seconds": reset_seconds,
            },
            headers=headers,
        )

    response = await call_next(request)
    response.headers.update(headers)
    return response


def _emotion_url(path):
    return f"{get_api_gateway_settings().emotion_api_base_url}/{path.lstrip('/')}"


def _auth_url(path):
    return f"{get_api_gateway_settings().auth_service_base_url}/{path.lstrip('/')}"


def _recommendation_url(path):
    return f"{get_api_gateway_settings().recommendation_service_base_url}/{path.lstrip('/')}"


def _analytics_url(path):
    return f"{get_api_gateway_settings().analytics_service_base_url}/{path.lstrip('/')}"


def _with_query(url, request):
    if request.url.query:
        return f"{url}?{request.url.query}"

    return url


def _forward_headers(request):
    headers = {}

    for name in ("accept", "authorization", "content-type"):
        value = request.headers.get(name)

        if value:
            headers[name] = value

    return headers


def _forward_headers_with_user(request, user):
    headers = _forward_headers(request)

    if user:
        headers["x-user-id"] = user["id"]

    return headers


async def request_downstream(method, url, headers=None, content=None):
    timeout = get_api_gateway_settings().request_timeout_seconds

    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(
            method,
            url,
            headers=headers,
            content=content,
        )


def _gateway_response(response):
    content_type = response.headers.get("content-type", "application/json")
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type,
    )


def _downstream_error_detail(service_name, exc):
    message = str(exc) or exc.__class__.__name__
    return f"{service_name} request failed: {message}"


async def _resolve_gateway_user(request):
    gateway_settings = get_api_gateway_settings()
    authorization = request.headers.get("authorization")

    if not authorization or not authorization.lower().startswith("bearer "):
        if gateway_settings.allow_anonymous_app_routes:
            return {"id": "anonymous", "email": None, "anonymous": True}

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Missing bearer token."},
        )

    try:
        auth_response = await request_downstream(
            "GET",
            _auth_url("/auth/me"),
            headers={
                "accept": "application/json",
                "authorization": authorization,
            },
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_downstream_error_detail("Auth service", exc),
        ) from exc

    if not auth_response.is_success:
        return _gateway_response(auth_response)

    try:
        payload = auth_response.json()
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "Auth service returned an invalid response."},
        )

    user = payload.get("user")

    if not user or not user.get("id"):
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "Auth service did not return a user id."},
        )

    return user


def _is_gateway_response(value):
    return isinstance(value, Response)


def _rate_limit_for_request(request):
    if request.method.upper() == "OPTIONS":
        return None

    path = request.url.path
    gateway_settings = get_api_gateway_settings()

    if path == "/api/health":
        return None

    if request.method.upper() == "POST" and path == "/api/auth/login":
        return "auth-login", gateway_settings.auth_login_rate_limit

    if request.method.upper() == "POST" and path == "/api/emotion/detect":
        return "emotion-detect", gateway_settings.emotion_detect_rate_limit

    if path == "/api/recommendation/from-emotion":
        return "recommendation-from-emotion", gateway_settings.recommendation_rate_limit

    client_ip = request.client.host if request.client else "unknown"
    return f"fallback:{request.method.upper()}:{path}", gateway_settings.fallback_rate_limit


def _rate_limit_identifier(request):
    forwarded_user_id = request.headers.get("x-user-id")

    if forwarded_user_id:
        return "user", forwarded_user_id

    authorization = request.headers.get("authorization", "")

    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return "token", token_hash

    client_ip = request.client.host if request.client else "unknown"
    return "ip", client_ip


def _rate_limit_headers(limit, remaining, reset_seconds):
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_seconds),
    }


def _cors_headers_for_request(request):
    origin = request.headers.get("origin")

    if not origin:
        return {}

    cors_origins = get_api_gateway_settings().cors_origins

    if "*" not in cors_origins and origin not in cors_origins:
        return {}

    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Expose-Headers": (
            "Retry-After, X-RateLimit-Limit, "
            "X-RateLimit-Remaining, X-RateLimit-Reset, X-RateLimit-Policy"
        ),
        "Vary": "Origin",
    }


def _inject_user_id_json_body(body, user_id):
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body

    if not isinstance(payload, dict):
        return body

    payload["user_id"] = user_id
    return json.dumps(payload).encode("utf-8")


def _url_with_trusted_user_id(url, user_id):
    parts = urlsplit(url)
    query_items = [
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if name != "user_id"
    ]
    query_items.append(("user_id", user_id))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_items), parts.fragment))


def _correlation_id(request):
    return (
        request.headers.get("x-correlation-id")
        or request.headers.get("x-request-id")
    )


async def _publish_gateway_event(request, event_type, user, payload):
    try:
        await get_event_producer().publish(
            EventEnvelope(
                event_type=event_type,
                source_service=get_api_gateway_settings().service_name,
                user_id=user["id"] if user else None,
                correlation_id=_correlation_id(request),
                payload=payload,
            )
        )
    except Exception:
        if not get_event_settings().kafka_fail_open:
            raise


def _emotion_detected_payload(response):
    try:
        payload = response.json()
    except ValueError:
        return None

    if not isinstance(payload, dict):
        return None

    return {
        "emotion": payload.get("emotion"),
        "confidence": payload.get("confidence"),
        "face": payload.get("face"),
    }


@app.get("/api/health")
async def health():
    gateway_settings = get_api_gateway_settings()
    status_value = "ok"
    rate_limiter_health = await get_rate_limit_cache().status()

    if rate_limiter_health["enabled"] and not rate_limiter_health["available"]:
        status_value = "degraded"

    try:
        emotion_response = await request_downstream(
            "GET",
            _emotion_url("/health"),
            headers={"accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        status_value = "degraded"
        emotion_health = {
            "status": "unavailable",
            "base_url": gateway_settings.emotion_api_base_url,
            "detail": str(exc),
        }
    else:
        emotion_payload = {}

        try:
            emotion_payload = emotion_response.json()
        except ValueError:
            emotion_payload = {"detail": emotion_response.text}

        if not emotion_response.is_success:
            status_value = "degraded"

        emotion_health = {
            "status_code": emotion_response.status_code,
            "base_url": gateway_settings.emotion_api_base_url,
            **emotion_payload,
        }

    try:
        auth_response = await request_downstream(
            "GET",
            _auth_url("/health"),
            headers={"accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        status_value = "degraded"
        auth_health = {
            "status": "unavailable",
            "base_url": gateway_settings.auth_service_base_url,
            "detail": str(exc),
        }
    else:
        auth_payload = {}

        try:
            auth_payload = auth_response.json()
        except ValueError:
            auth_payload = {"detail": auth_response.text}

        if not auth_response.is_success or auth_payload.get("status") != "ok":
            status_value = "degraded"

        auth_health = {
            "status_code": auth_response.status_code,
            "base_url": gateway_settings.auth_service_base_url,
            **auth_payload,
        }

    try:
        recommendation_response = await request_downstream(
            "GET",
            _recommendation_url("/health"),
            headers={"accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        status_value = "degraded"
        recommendation_health = {
            "status": "unavailable",
            "base_url": gateway_settings.recommendation_service_base_url,
            "detail": str(exc),
        }
    else:
        recommendation_payload = {}

        try:
            recommendation_payload = recommendation_response.json()
        except ValueError:
            recommendation_payload = {"detail": recommendation_response.text}

        if (
            not recommendation_response.is_success
            or recommendation_payload.get("status") != "ok"
        ):
            status_value = "degraded"

        recommendation_health = {
            "status_code": recommendation_response.status_code,
            "base_url": gateway_settings.recommendation_service_base_url,
            **recommendation_payload,
        }

    try:
        analytics_response = await request_downstream(
            "GET",
            _analytics_url("/health"),
            headers={"accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        status_value = "degraded"
        analytics_health = {
            "status": "unavailable",
            "base_url": gateway_settings.analytics_service_base_url,
            "detail": str(exc),
        }
    else:
        analytics_payload = {}

        try:
            analytics_payload = analytics_response.json()
        except ValueError:
            analytics_payload = {"detail": analytics_response.text}

        if (
            not analytics_response.is_success
            or analytics_payload.get("status") != "ok"
        ):
            status_value = "degraded"

        analytics_health = {
            "status_code": analytics_response.status_code,
            "base_url": gateway_settings.analytics_service_base_url,
            **analytics_payload,
        }

    return {
        "status": status_value,
        "service": gateway_settings.service_name,
        "emotion_api": emotion_health,
        "auth_service": auth_health,
        "recommendation_service": recommendation_health,
        "analytics_service": analytics_health,
        "rate_limiter": rate_limiter_health,
    }


@app.api_route("/api/emotion/{path:path}", methods=["GET", "POST"])
async def proxy_emotion(path: str, request: Request):
    user = await _resolve_gateway_user(request)

    if _is_gateway_response(user):
        return user

    method = request.method
    body = await request.body()
    is_detection_request = method.upper() == "POST" and path == "detect"

    if is_detection_request:
        await _publish_gateway_event(
            request,
            "camera.capture",
            user,
            {
                "route": "/api/emotion/detect",
                "content_type": request.headers.get("content-type"),
            },
        )

    try:
        downstream_response = await request_downstream(
            method,
            _with_query(_emotion_url(f"/emotion/{path}"), request),
            headers=_forward_headers_with_user(request, user),
            content=body if body else None,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_downstream_error_detail("Emotion API", exc),
        ) from exc

    if is_detection_request and downstream_response.is_success:
        payload = _emotion_detected_payload(downstream_response)

        if payload:
            await _publish_gateway_event(
                request,
                "emotion.detected",
                user,
                payload,
            )

    return _gateway_response(downstream_response)


@app.api_route("/api/recommendation/{path:path}", methods=["GET", "POST"])
async def proxy_recommendation(path: str, request: Request):
    user = await _resolve_gateway_user(request)

    if _is_gateway_response(user):
        return user

    method = request.method
    body = await request.body()
    content = body if body else None
    url = _with_query(_recommendation_url(f"/recommendation/{path}"), request)

    if path == "from-emotion":
        if method == "POST" and request.headers.get("content-type", "").startswith("application/json"):
            content = _inject_user_id_json_body(body, user["id"])
        elif method == "GET":
            url = _url_with_trusted_user_id(url, user["id"])
    elif path == "current-emotion" and method == "GET":
        url = _url_with_trusted_user_id(url, user["id"])

    try:
        downstream_response = await request_downstream(
            method,
            url,
            headers=_forward_headers_with_user(request, user),
            content=content,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_downstream_error_detail("Recommendation service", exc),
        ) from exc

    return _gateway_response(downstream_response)


@app.post("/api/playback/event")
async def proxy_playback_event(request: Request):
    user = await _resolve_gateway_user(request)

    if _is_gateway_response(user):
        return user

    body = await request.body()
    content = body if body else None

    if request.headers.get("content-type", "").startswith("application/json"):
        content = _inject_user_id_json_body(body, user["id"])

    try:
        downstream_response = await request_downstream(
            "POST",
            _recommendation_url("/recommendation/playback/event"),
            headers=_forward_headers_with_user(request, user),
            content=content,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_downstream_error_detail("Recommendation service", exc),
        ) from exc

    return _gateway_response(downstream_response)


@app.api_route("/api/analytics/{path:path}", methods=["GET"])
async def proxy_analytics(path: str, request: Request):
    user = await _resolve_gateway_user(request)

    if _is_gateway_response(user):
        return user

    try:
        downstream_response = await request_downstream(
            request.method,
            _with_query(_analytics_url(f"/analytics/{path}"), request),
            headers=_forward_headers_with_user(request, user),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_downstream_error_detail("Analytics service", exc),
        ) from exc

    return _gateway_response(downstream_response)


@app.api_route("/api/auth/{path:path}", methods=["GET", "POST"])
async def proxy_auth(path: str, request: Request):
    method = request.method
    body = await request.body()

    try:
        downstream_response = await request_downstream(
            method,
            _with_query(_auth_url(f"/auth/{path}"), request),
            headers=_forward_headers(request),
            content=body if body else None,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_downstream_error_detail("Auth service", exc),
        ) from exc

    return _gateway_response(downstream_response)
