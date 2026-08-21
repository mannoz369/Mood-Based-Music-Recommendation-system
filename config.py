import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_EMOTION_MODEL_PATH = (
    PROJECT_ROOT / "models" / "fer2013_mini_XCEPTION.102-0.66.hdf5"
)


def _load_dotenv_file(path=ENV_FILE):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")

        if name and name not in os.environ:
            os.environ[name] = value


_load_dotenv_file()


@dataclass(frozen=True)
class EmotionApiSettings:
    service_name: str
    model_path: Path
    min_detection_confidence: float
    max_upload_bytes: int
    cors_origins: tuple[str, ...]


@dataclass(frozen=True)
class ApiGatewaySettings:
    service_name: str
    emotion_api_base_url: str
    auth_service_base_url: str
    recommendation_service_base_url: str
    analytics_service_base_url: str
    redis_url: str | None
    redis_namespace: str
    redis_fail_open: bool
    request_timeout_seconds: float
    rate_limit_window_seconds: int
    auth_login_rate_limit: int
    emotion_detect_rate_limit: int
    recommendation_rate_limit: int
    fallback_rate_limit: int
    allow_anonymous_app_routes: bool
    cors_origins: tuple[str, ...]


@dataclass(frozen=True)
class AuthSettings:
    service_name: str
    mongodb_uri: str | None
    mongodb_database: str
    users_collection: str
    jwt_secret: str
    jwt_issuer: str
    jwt_expires_minutes: int
    cors_origins: tuple[str, ...]


@dataclass(frozen=True)
class AnalyticsSettings:
    service_name: str
    mongodb_uri: str | None
    mongodb_database: str
    events_collection: str
    mood_timeline_collection: str
    recommendation_history_collection: str
    playback_history_collection: str
    fail_open: bool


@dataclass(frozen=True)
class RecommendationSettings:
    service_name: str
    jamendo_client_id: str | None
    jamendo_api_base_url: str
    redis_url: str | None
    redis_namespace: str
    redis_fail_open: bool
    request_timeout_seconds: float
    default_limit: int
    cache_ttl_seconds: int
    cooldown_seconds: int
    recent_track_limit: int
    recent_track_ttl_seconds: int
    cors_origins: tuple[str, ...]


@dataclass(frozen=True)
class EventSettings:
    kafka_enabled: bool
    kafka_bootstrap_servers: str | None
    kafka_client_id: str
    kafka_fail_open: bool
    kafka_consumer_group_id: str = "emotion-music-ai-recommendation"
    recommendation_precompute_enabled: bool = True


def _get_float(name, default):
    value = os.getenv(name)

    if value is None:
        return default

    return float(value)


def _get_int(name, default):
    value = os.getenv(name)

    if value is None:
        return default

    return int(value)


def _get_bool(name, default):
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_csv(name, default):
    value = os.getenv(name)

    if value is None:
        return default

    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


def get_emotion_api_settings():
    return EmotionApiSettings(
        service_name=os.getenv("EMOTION_API_SERVICE_NAME", "emotion-api"),
        model_path=Path(
            os.getenv("EMOTION_MODEL_PATH", str(DEFAULT_EMOTION_MODEL_PATH))
        ),
        min_detection_confidence=_get_float("FACE_MIN_DETECTION_CONFIDENCE", 0.6),
        max_upload_bytes=_get_int("EMOTION_API_MAX_UPLOAD_BYTES", 5 * 1024 * 1024),
        cors_origins=_get_csv(
            "EMOTION_API_CORS_ORIGINS",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
    )


def get_api_gateway_settings():
    return ApiGatewaySettings(
        service_name=os.getenv("API_GATEWAY_SERVICE_NAME", "api-gateway"),
        emotion_api_base_url=os.getenv(
            "EMOTION_API_BASE_URL", "http://127.0.0.1:8000"
        ).rstrip("/"),
        auth_service_base_url=os.getenv(
            "AUTH_SERVICE_BASE_URL", "http://127.0.0.1:8002"
        ).rstrip("/"),
        recommendation_service_base_url=os.getenv(
            "RECOMMENDATION_SERVICE_BASE_URL", "http://127.0.0.1:8004"
        ).rstrip("/"),
        analytics_service_base_url=os.getenv(
            "ANALYTICS_SERVICE_BASE_URL", "http://127.0.0.1:8005"
        ).rstrip("/"),
        redis_url=os.getenv("REDIS_URL") or None,
        redis_namespace=os.getenv("REDIS_NAMESPACE", "emotion-music-ai"),
        redis_fail_open=_get_bool("REDIS_FAIL_OPEN", True),
        request_timeout_seconds=_get_float("API_GATEWAY_REQUEST_TIMEOUT_SECONDS", 60.0),
        rate_limit_window_seconds=_get_int("API_GATEWAY_RATE_LIMIT_WINDOW_SECONDS", 60),
        auth_login_rate_limit=_get_int("API_GATEWAY_AUTH_LOGIN_RATE_LIMIT", 5),
        emotion_detect_rate_limit=_get_int("API_GATEWAY_EMOTION_DETECT_RATE_LIMIT", 10),
        recommendation_rate_limit=_get_int("API_GATEWAY_RECOMMENDATION_RATE_LIMIT", 20),
        fallback_rate_limit=_get_int("API_GATEWAY_FALLBACK_RATE_LIMIT", 120),
        allow_anonymous_app_routes=_get_bool("API_GATEWAY_ALLOW_ANONYMOUS_APP_ROUTES", False),
        cors_origins=_get_csv(
            "API_GATEWAY_CORS_ORIGINS",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
    )


def get_auth_settings():
    return AuthSettings(
        service_name=os.getenv("AUTH_SERVICE_NAME", "auth-service"),
        mongodb_uri=os.getenv("MONGODB_URI") or None,
        mongodb_database=os.getenv("MONGODB_DATABASE", "emotion_music_ai"),
        users_collection=os.getenv("MONGODB_USERS_COLLECTION", "users"),
        jwt_secret=os.getenv("JWT_SECRET", "dev-only-change-me"),
        jwt_issuer=os.getenv("JWT_ISSUER", "emotion-music-ai"),
        jwt_expires_minutes=_get_int("JWT_EXPIRES_MINUTES", 60),
        cors_origins=_get_csv(
            "AUTH_SERVICE_CORS_ORIGINS",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
    )


def get_analytics_settings():
    return AnalyticsSettings(
        service_name=os.getenv("ANALYTICS_SERVICE_NAME", "analytics-service"),
        mongodb_uri=os.getenv("MONGODB_URI") or None,
        mongodb_database=os.getenv("MONGODB_DATABASE", "emotion_music_ai"),
        events_collection=os.getenv("ANALYTICS_EVENTS_COLLECTION", "analytics_events"),
        mood_timeline_collection=os.getenv(
            "ANALYTICS_MOOD_TIMELINE_COLLECTION",
            "user_mood_timeline",
        ),
        recommendation_history_collection=os.getenv(
            "ANALYTICS_RECOMMENDATION_HISTORY_COLLECTION",
            "user_recommendation_history",
        ),
        playback_history_collection=os.getenv(
            "ANALYTICS_PLAYBACK_HISTORY_COLLECTION",
            "user_playback_history",
        ),
        fail_open=_get_bool("ANALYTICS_FAIL_OPEN", True),
    )


def get_recommendation_settings():
    return RecommendationSettings(
        service_name=os.getenv("RECOMMENDATION_SERVICE_NAME", "recommendation-service"),
        jamendo_client_id=os.getenv("JAMENDO_CLIENT_ID") or None,
        jamendo_api_base_url=os.getenv(
            "JAMENDO_API_BASE_URL", "https://api.jamendo.com/v3.0"
        ).rstrip("/"),
        redis_url=os.getenv("REDIS_URL") or None,
        redis_namespace=os.getenv("REDIS_NAMESPACE", "emotion-music-ai"),
        redis_fail_open=_get_bool("REDIS_FAIL_OPEN", True),
        request_timeout_seconds=_get_float("RECOMMENDATION_REQUEST_TIMEOUT_SECONDS", 30.0),
        default_limit=_get_int("RECOMMENDATION_DEFAULT_LIMIT", 10),
        cache_ttl_seconds=_get_int("RECOMMENDATION_CACHE_TTL_SECONDS", 600),
        cooldown_seconds=_get_int("RECOMMENDATION_COOLDOWN_SECONDS", 60),
        recent_track_limit=_get_int("RECOMMENDATION_RECENT_TRACK_LIMIT", 50),
        recent_track_ttl_seconds=_get_int("RECOMMENDATION_RECENT_TRACK_TTL_SECONDS", 86400),
        cors_origins=_get_csv(
            "RECOMMENDATION_SERVICE_CORS_ORIGINS",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
    )


def get_event_settings():
    return EventSettings(
        kafka_enabled=_get_bool("KAFKA_ENABLED", False),
        kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS") or None,
        kafka_client_id=os.getenv("KAFKA_CLIENT_ID", "emotion-music-ai"),
        kafka_fail_open=_get_bool("KAFKA_FAIL_OPEN", True),
        kafka_consumer_group_id=os.getenv(
            "KAFKA_CONSUMER_GROUP_ID",
            "emotion-music-ai-recommendation",
        ),
        recommendation_precompute_enabled=_get_bool(
            "RECOMMENDATION_PRECOMPUTE_ENABLED",
            True,
        ),
    )
