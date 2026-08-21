import hashlib
from datetime import datetime, timezone

from services.events import EventEnvelope
from services.recommendation.intents import (
    EMOTION_INTENTS,
    get_intent_for_emotion,
    get_profile_variants_for_emotion,
)


class RecommendationService:
    def __init__(self, music_client, settings, cache=None, event_producer=None):
        self.music_client = music_client
        self.settings = settings
        self.cache = cache
        self.event_producer = event_producer

    def metadata(self):
        return {
            "service": self.settings.service_name,
            "supported_emotions": list(EMOTION_INTENTS.keys()),
            "intents": EMOTION_INTENTS,
            "default_limit": self.settings.default_limit,
            "provider": "jamendo",
            "cache": {
                "ttl_seconds": self.settings.cache_ttl_seconds,
                "cooldown_seconds": self.settings.cooldown_seconds,
            },
        }

    async def cache_status(self):
        if not self.cache:
            return {
                "enabled": False,
                "available": False,
                "detail": "Recommendation cache is not configured.",
            }

        return await self.cache.status()

    async def current_emotion(self, user_id="anonymous"):
        if not self.cache:
            return None

        payload = await self.cache.get_current_emotion(user_id)

        if not payload:
            return None

        return payload.get("emotion")

    async def record_playback_event(
        self,
        event_type,
        track_id,
        user_id="anonymous",
        emotion=None,
        provider="jamendo",
        publish_event=True,
    ):
        if event_type not in {"started", "paused", "skipped", "ended"}:
            raise ValueError(f"Unsupported playback event type: {event_type}")

        if not track_id:
            raise ValueError("track_id is required.")

        if self.cache and event_type in {"started", "skipped", "ended"}:
            await self.cache.remember_recent_track_id(
                user_id,
                track_id,
                kind="played",
                limit=self.settings.recent_track_limit,
                ttl_seconds=self.settings.recent_track_ttl_seconds,
            )

        response = {
            "status": "ok",
            "event_type": event_type,
            "track_id": str(track_id),
            "emotion": emotion,
            "provider": provider or "jamendo",
        }
        if publish_event:
            await self._publish_event(
                "playback.event",
                user_id,
                {
                    "event_type": event_type,
                    "track_id": str(track_id),
                    "emotion": emotion,
                    "provider": provider or "jamendo",
                },
            )
        return response

    async def handle_emotion_detected_event(self, event, precompute=True):
        payload = event.get("payload") or {}
        user_id = event.get("user_id") or payload.get("user_id") or "anonymous"
        emotion = payload.get("emotion")

        if not emotion:
            return {
                "status": "skipped",
                "reason": "emotion is missing.",
            }

        current_emotion = await self.current_emotion(user_id)
        cooldown = (
            await self.cache.get_cooldown(user_id, emotion)
            if self.cache
            else {"active": False, "ttl_seconds": None}
        )

        if current_emotion == emotion and cooldown["active"]:
            return {
                "status": "skipped",
                "reason": "cooldown-active",
                "emotion": emotion,
                "user_id": user_id,
                "cooldown": cooldown,
            }

        if not precompute:
            if self.cache:
                await self.cache.set_current_emotion(
                    user_id,
                    emotion,
                    ttl_seconds=self.settings.cooldown_seconds,
                )
                await self.cache.set_cooldown(
                    user_id,
                    emotion,
                    ttl_seconds=self.settings.cooldown_seconds,
                )

            return {
                "status": "updated",
                "emotion": emotion,
                "user_id": user_id,
                "precomputed": False,
            }

        response = await self.from_emotion(
            emotion,
            limit=payload.get("limit"),
            user_id=user_id,
            language=payload.get("language"),
            request_seed=event.get("event_id") or event.get("correlation_id"),
        )
        await self._publish_recommendation_generated(user_id, response, event)
        return {
            "status": "generated",
            "emotion": emotion,
            "user_id": user_id,
            "cache": response.get("cache"),
            "track_count": len(response.get("tracks", [])),
        }

    async def handle_playback_event(self, event):
        payload = event.get("payload") or {}
        return await self.record_playback_event(
            payload.get("event_type"),
            payload.get("track_id"),
            user_id=event.get("user_id") or payload.get("user_id") or "anonymous",
            emotion=payload.get("emotion"),
            provider=payload.get("provider") or "jamendo",
            publish_event=False,
        )

    async def from_emotion(
        self,
        emotion,
        limit=None,
        user_id="anonymous",
        language=None,
        request_seed=None,
    ):
        intent = get_intent_for_emotion(emotion)
        resolved_limit = limit or self.settings.default_limit
        resolved_language = self._normalize_language(language)
        recent_recommended_ids = await self._recent_track_ids(user_id, kind="recommended")
        recent_played_ids = await self._recent_track_ids(user_id, kind="played")
        await self._publish_event(
            "recommendation.requested",
            user_id,
            {
                "emotion": emotion,
                "limit": resolved_limit,
                "language": resolved_language or "any",
                "request_seed": request_seed,
                "recent_recommended_track_count": len(recent_recommended_ids),
                "recent_played_track_count": len(recent_played_ids),
            },
        )
        query_contexts = self._dynamic_query_contexts(
            emotion,
            intent,
            user_id,
            resolved_language,
            request_seed=request_seed,
            recent_recommended_ids=recent_recommended_ids,
            recent_played_ids=recent_played_ids,
        )
        candidate_limit = self._candidate_limit(resolved_limit)
        empty_response = None

        for query_context in query_contexts:
            cache_key = self._recommendation_cache_key(
                user_id,
                emotion,
                resolved_limit,
                resolved_language,
                query_context["query_signature"],
            )
            cached_response = await self._cached_response(cache_key)

            if cached_response:
                cached_response["cache"] = {
                    "hit": True,
                    "key": cache_key,
                    "ttl_seconds": self.settings.cache_ttl_seconds,
                    "cooldown_seconds": self.settings.cooldown_seconds,
                }
                await self._remember_recommended_tracks(
                    user_id,
                    cached_response.get("tracks", []),
                )
                await self._publish_recommendation_served(user_id, cached_response)
                return cached_response

            tracks = await self.music_client.search_tracks(
                query_context["query"],
                candidate_limit,
                language=resolved_language,
            )
            ranked_tracks = self._rank_tracks(
                tracks,
                resolved_limit,
                excluded_track_ids=set(recent_recommended_ids) | set(recent_played_ids),
            )
            response = {
                "emotion": emotion,
                "intent": intent,
                "provider": "jamendo",
                "language": resolved_language or "any",
                "query": query_context["query"],
                "query_seed": query_context["query_seed"],
                "dynamic_profile": query_context["dynamic_profile"],
                "tracks": ranked_tracks,
                "cache": {
                    "hit": False,
                    "key": cache_key,
                    "ttl_seconds": self.settings.cache_ttl_seconds,
                    "cooldown_seconds": self.settings.cooldown_seconds,
                },
            }

            if ranked_tracks:
                await self._write_cache(cache_key, response, user_id, emotion)
                await self._remember_recommended_tracks(user_id, ranked_tracks)
                await self._publish_recommendation_served(user_id, response)
                return response

            empty_response = (cache_key, response)

        cache_key, response = empty_response
        await self._write_cache(cache_key, response, user_id, emotion)
        await self._publish_recommendation_served(user_id, response)
        return response

    async def _publish_event(self, event_type, user_id, payload, correlation_id=None):
        if not self.event_producer:
            return

        try:
            await self.event_producer.publish(
                EventEnvelope(
                    event_type=event_type,
                    source_service=self.settings.service_name,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    payload=payload,
                )
            )
        except Exception:
            producer_settings = getattr(self.event_producer, "settings", None)

            if not getattr(producer_settings, "kafka_fail_open", True):
                raise

    async def _publish_recommendation_served(self, user_id, response):
        await self._publish_event(
            "recommendation.served",
            user_id,
            {
                "emotion": response.get("emotion"),
                "provider": response.get("provider"),
                "language": response.get("language"),
                "query": response.get("query"),
                "query_seed": response.get("query_seed"),
                "dynamic_profile": response.get("dynamic_profile"),
                "track_ids": [
                    str(track_id)
                    for track_id in (
                        track.get("id") or track.get("uri")
                        for track in response.get("tracks", [])
                    )
                    if track_id
                ],
                "cache": response.get("cache"),
            },
        )

    async def _publish_recommendation_generated(self, user_id, response, trigger_event):
        await self._publish_event(
            "recommendation.generated",
            user_id,
            {
                "emotion": response.get("emotion"),
                "provider": response.get("provider"),
                "language": response.get("language"),
                "query": response.get("query"),
                "query_seed": response.get("query_seed"),
                "dynamic_profile": response.get("dynamic_profile"),
                "track_ids": [
                    str(track_id)
                    for track_id in (
                        track.get("id") or track.get("uri")
                        for track in response.get("tracks", [])
                    )
                    if track_id
                ],
                "cache": response.get("cache"),
                "trigger_event_id": trigger_event.get("event_id"),
                "trigger_event_type": trigger_event.get("event_type"),
            },
            correlation_id=trigger_event.get("correlation_id"),
        )

    def _dynamic_query_contexts(
        self,
        emotion,
        intent,
        user_id,
        language,
        request_seed=None,
        recent_recommended_ids=None,
        recent_played_ids=None,
    ):
        variants = get_profile_variants_for_emotion(emotion)
        query_seed = ":".join(
            self._query_seed_parts(
                emotion,
                user_id,
                language,
                request_seed=request_seed,
                recent_recommended_ids=recent_recommended_ids,
                recent_played_ids=recent_played_ids,
            )
        )
        digest = hashlib.sha256(query_seed.encode("utf-8")).hexdigest()
        selected_index = int(digest[:8], 16) % len(variants)
        ordered_indices = [selected_index] + [
            index for index in range(len(variants)) if index != selected_index
        ]

        return [
            self._dynamic_query_context(
                emotion,
                intent,
                user_id,
                language,
                request_seed=request_seed,
                recent_recommended_ids=recent_recommended_ids,
                recent_played_ids=recent_played_ids,
                variant_index=index,
            )
            for index in ordered_indices
        ]

    def _dynamic_query_context(
        self,
        emotion,
        intent,
        user_id,
        language,
        request_seed=None,
        recent_recommended_ids=None,
        recent_played_ids=None,
        variant_index=None,
    ):
        variants = get_profile_variants_for_emotion(emotion)
        seed_parts = self._query_seed_parts(
            emotion,
            user_id,
            language,
            request_seed=request_seed,
            recent_recommended_ids=recent_recommended_ids,
            recent_played_ids=recent_played_ids,
        )
        query_seed = ":".join(seed_parts)
        digest = hashlib.sha256(query_seed.encode("utf-8")).hexdigest()
        selected_index = int(digest[:8], 16) % len(variants) if variant_index is None else variant_index
        variant = variants[selected_index]
        signature_source = f"{query_seed}:{variant['variant']}"
        query_signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest()[:16]
        dynamic_profile = {
            "intent": intent["intent"],
            "energy": variant["energy"],
            "variant": variant["variant"],
            "genre": variant["genre"],
            "instrument": variant["instrument"],
            "tempo": variant["tempo"],
            "vibe": variant["vibe"],
        }

        return {
            "query": variant["query"],
            "query_seed": query_seed,
            "query_signature": query_signature,
            "dynamic_profile": dynamic_profile,
        }

    def _query_seed_parts(
        self,
        emotion,
        user_id,
        language,
        request_seed=None,
        recent_recommended_ids=None,
        recent_played_ids=None,
    ):
        timestamp_bucket = self._timestamp_bucket()
        return [
            str(request_seed or timestamp_bucket),
            self._normalize_cache_part(user_id),
            emotion,
            language or "any",
            ",".join(sorted(str(track_id) for track_id in recent_recommended_ids or [])),
            ",".join(sorted(str(track_id) for track_id in recent_played_ids or [])),
        ]

    def _rank_tracks(self, tracks, limit, excluded_track_ids=None):
        excluded_track_ids = {str(track_id) for track_id in excluded_track_ids or []}
        seen = set()
        fallback_ranked = []
        filtered_ranked = []

        for track in tracks:
            track_id = track.get("id") or track.get("uri")

            if track_id in seen:
                continue

            seen.add(track_id)
            fallback_ranked.append(track)

            if str(track_id) not in excluded_track_ids:
                filtered_ranked.append(track)

        ranked = filtered_ranked if filtered_ranked else fallback_ranked

        return ranked[:limit]

    async def _cached_response(self, cache_key):
        if not self.cache:
            return None

        return await self.cache.get_json(cache_key)

    async def _write_cache(self, cache_key, response, user_id, emotion):
        if not self.cache:
            return

        payload = dict(response)
        payload.pop("cache", None)
        await self.cache.set_json(
            cache_key,
            payload,
            ttl_seconds=max(self.settings.cache_ttl_seconds, self.settings.cooldown_seconds),
        )
        await self.cache.set_current_emotion(
            user_id,
            emotion,
            ttl_seconds=self.settings.cooldown_seconds,
        )
        await self.cache.set_cooldown(user_id, emotion, ttl_seconds=self.settings.cooldown_seconds)

    async def _remember_recommended_tracks(self, user_id, tracks):
        if not self.cache:
            return

        track_ids = [track.get("id") or track.get("uri") for track in tracks]
        await self.cache.remember_recent_track_ids(
            user_id,
            [track_id for track_id in track_ids if track_id],
            kind="recommended",
            limit=self.settings.recent_track_limit,
            ttl_seconds=self.settings.recent_track_ttl_seconds,
        )

    async def _recent_track_ids(self, user_id, kind):
        if not self.cache:
            return []

        return await self.cache.get_recent_track_ids(user_id, kind=kind)

    def _recommendation_cache_key(self, user_id, emotion, limit, language=None, query_signature=None):
        if self.cache:
            return self.cache.recommendation_key(
                user_id,
                emotion,
                limit,
                language,
                query_signature or "static",
            )

        return (
            f"recommendations:{self._normalize_cache_part(user_id)}:"
            f"{emotion}:{limit}:{self._normalize_cache_part(language or 'any')}:"
            f"{self._normalize_cache_part(query_signature or 'static')}"
        )

    def _current_emotion_key(self, user_id):
        return f"current-emotion:{self._normalize_cache_part(user_id)}"

    def _cooldown_key(self, user_id, emotion):
        return f"cooldown:{self._normalize_cache_part(user_id)}:{emotion}"

    def _normalize_cache_part(self, value):
        return str(value or "anonymous").strip().lower().replace(" ", "-")

    def _normalize_language(self, language):
        if not language:
            return None

        normalized = str(language).strip().lower()
        return normalized or None

    def _timestamp_bucket(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")

    def _candidate_limit(self, limit):
        return max(limit, min(limit * 3, 25))
