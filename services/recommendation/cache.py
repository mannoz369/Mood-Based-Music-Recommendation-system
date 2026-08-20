import json


class RecommendationCache:
    def __init__(self, redis_url, namespace="emotion-music-ai", fail_open=True):
        self.redis_url = redis_url
        self.namespace = namespace
        self.fail_open = fail_open
        self._redis = None

    async def status(self):
        if not self.redis_url:
            return {
                "enabled": False,
                "available": False,
                "detail": "REDIS_URL is not configured.",
                "fail_open": self.fail_open,
            }

        try:
            client = await self._client()
            await client.ping()
        except Exception as exc:
            return {
                "enabled": True,
                "available": False,
                "detail": str(exc) or exc.__class__.__name__,
                "fail_open": self.fail_open,
            }

        return {
            "enabled": True,
            "available": True,
            "detail": "connected",
            "fail_open": self.fail_open,
        }

    async def get_json(self, key):
        raw_value = await self.get_text(key)

        if raw_value is None:
            return None

        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key, value, ttl_seconds=None):
        return await self.set_text(key, json.dumps(value), ttl_seconds=ttl_seconds)

    async def get_text(self, key):
        if not self.redis_url:
            return None

        try:
            client = await self._client()
            raw_value = await client.get(self._key(key))
        except Exception:
            return None

        if isinstance(raw_value, bytes):
            return raw_value.decode("utf-8")

        return raw_value

    async def set_text(self, key, value, ttl_seconds=None):
        if not self.redis_url:
            return False

        try:
            client = await self._client()
            await client.set(self._key(key), value, ex=ttl_seconds)
        except Exception:
            return False

        return True

    async def increment_counter(self, key, ttl_seconds):
        if not self.redis_url:
            return None

        try:
            client = await self._client()
            count = await client.incr(self._key(key))

            if count == 1 and ttl_seconds:
                await client.expire(self._key(key), ttl_seconds)
        except Exception:
            return None

        return int(count)

    async def ttl(self, key):
        if not self.redis_url:
            return None

        try:
            client = await self._client()
            value = await client.ttl(self._key(key))
        except Exception:
            return None

        return int(value)

    async def get_current_emotion(self, user_id):
        return await self.get_json(self.current_emotion_key(user_id))

    async def set_current_emotion(self, user_id, emotion, ttl_seconds=None):
        return await self.set_json(
            self.current_emotion_key(user_id),
            {"emotion": emotion},
            ttl_seconds=ttl_seconds,
        )

    async def get_cooldown(self, user_id, emotion):
        key = self.cooldown_key(user_id, emotion)
        active = await self.get_text(key)

        if active is None:
            return {"active": False, "ttl_seconds": None}

        return {
            "active": True,
            "ttl_seconds": await self.ttl(key),
        }

    async def set_cooldown(self, user_id, emotion, ttl_seconds):
        return await self.set_text(
            self.cooldown_key(user_id, emotion),
            "1",
            ttl_seconds=ttl_seconds,
        )

    async def get_recent_track_ids(self, user_id, kind="recommended"):
        if not self.redis_url:
            return []

        try:
            client = await self._client()
            values = await client.lrange(self._key(self.recent_tracks_key(user_id, kind)), 0, -1)
        except Exception:
            return []

        return [value.decode("utf-8") if isinstance(value, bytes) else value for value in values]

    async def remember_recent_track_id(
        self,
        user_id,
        track_id,
        kind="recommended",
        limit=50,
        ttl_seconds=86400,
    ):
        if not self.redis_url or not track_id:
            return False

        key = self.recent_tracks_key(user_id, kind)

        try:
            client = await self._client()
            await client.lpush(self._key(key), str(track_id))
            await client.ltrim(self._key(key), 0, max(limit - 1, 0))
            await client.expire(self._key(key), ttl_seconds)
        except Exception:
            return False

        return True

    async def remember_recent_track_ids(
        self,
        user_id,
        track_ids,
        kind="recommended",
        limit=50,
        ttl_seconds=86400,
    ):
        saved_any = False

        for track_id in track_ids:
            saved = await self.remember_recent_track_id(
                user_id,
                track_id,
                kind=kind,
                limit=limit,
                ttl_seconds=ttl_seconds,
            )
            saved_any = saved_any or saved

        return saved_any

    def rate_limit_key(self, scope, identifier):
        return f"rate-limit:{self._normalize_part(scope)}:{self._normalize_part(identifier)}"

    def current_emotion_key(self, user_id):
        return f"current-emotion:{self._normalize_part(user_id)}"

    def cooldown_key(self, user_id, emotion):
        return f"cooldown:{self._normalize_part(user_id)}:{self._normalize_part(emotion)}"

    def recommendation_key(self, user_id, emotion, limit, language, query_signature):
        return (
            f"recommendations:{self._normalize_part(user_id)}:"
            f"{self._normalize_part(emotion)}:{limit}:"
            f"{self._normalize_part(language or 'any')}:"
            f"{self._normalize_part(query_signature)}"
        )

    def recent_tracks_key(self, user_id, kind="recommended"):
        normalized_kind = self._normalize_part(kind)

        if normalized_kind not in {"recommended", "played"}:
            raise ValueError("Recent track kind must be 'recommended' or 'played'.")

        return f"recent-{normalized_kind}-tracks:{self._normalize_part(user_id)}"

    async def _client(self):
        if self._redis:
            return self._redis

        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Redis dependency is not installed. Run `python -m pip install -r requirements.txt`."
            ) from exc

        self._redis = Redis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def _key(self, key):
        return f"{self.namespace}:{key}"

    def _normalize_part(self, value):
        return str(value or "anonymous").strip().lower().replace(" ", "-")
