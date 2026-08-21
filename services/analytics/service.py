import json
from datetime import datetime, timezone


class AnalyticsService:
    def __init__(self, repository, settings):
        self.repository = repository
        self.settings = settings

    async def ensure_ready(self):
        await self.repository.ensure_indexes()

    async def health_check(self):
        await self.repository.health_check()

    async def moods_for_user(self, user_id, limit=50):
        return {
            "user_id": user_id,
            "moods": await self.repository.list_moods(user_id, limit=limit),
        }

    async def recommendations_for_user(self, user_id, limit=50):
        return {
            "user_id": user_id,
            "recommendations": await self.repository.list_recommendations(
                user_id,
                limit=limit,
            ),
        }

    async def playback_for_user(self, user_id, limit=50):
        return {
            "user_id": user_id,
            "playback": await self.repository.list_playback(user_id, limit=limit),
        }

    async def summary_for_user(self, user_id):
        moods = await self.repository.list_moods(user_id, limit=50)
        recommendations = await self.repository.list_recommendations(user_id, limit=50)
        playback = await self.repository.list_playback(user_id, limit=50)
        playback_actions = {}

        for event in playback:
            action = event.get("action") or "unknown"
            playback_actions[action] = playback_actions.get(action, 0) + 1

        return {
            "user_id": user_id,
            "latest_mood": moods[0] if moods else None,
            "counts": {
                "moods": len(moods),
                "recommendations": len(recommendations),
                "playback": len(playback),
            },
            "playback_actions": playback_actions,
        }

    async def handle_event(self, event):
        normalized_event = self._normalize_event(event)
        event_type = normalized_event.get("event_type")
        payload = normalized_event.get("payload") or {}
        stored = ["analytics_events"]

        await self.repository.store_event(self._raw_event_document(normalized_event))

        if event_type == "emotion.detected":
            await self.repository.store_mood_timeline(
                self._mood_timeline_document(normalized_event, payload)
            )
            stored.append("user_mood_timeline")
        elif event_type in {
            "recommendation.requested",
            "recommendation.generated",
            "recommendation.served",
        }:
            await self.repository.store_recommendation_history(
                self._recommendation_history_document(normalized_event, payload)
            )
            stored.append("user_recommendation_history")
        elif event_type == "playback.event":
            await self.repository.store_playback_history(
                self._playback_history_document(normalized_event, payload)
            )
            stored.append("user_playback_history")

        return {
            "status": "stored",
            "event_type": event_type,
            "event_id": normalized_event.get("event_id"),
            "collections": stored,
        }

    def _raw_event_document(self, event):
        return {
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "schema_version": event.get("schema_version"),
            "occurred_at": event.get("occurred_at"),
            "ingested_at": self._now(),
            "user_id": event.get("user_id"),
            "correlation_id": event.get("correlation_id"),
            "source_service": event.get("source_service"),
            "payload": event.get("payload") or {},
        }

    def _mood_timeline_document(self, event, payload):
        return {
            "event_id": event.get("event_id"),
            "user_id": event.get("user_id") or payload.get("user_id") or "anonymous",
            "emotion": payload.get("emotion"),
            "confidence": payload.get("confidence"),
            "face": payload.get("face"),
            "occurred_at": event.get("occurred_at"),
            "ingested_at": self._now(),
            "correlation_id": event.get("correlation_id"),
        }

    def _recommendation_history_document(self, event, payload):
        return {
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "user_id": event.get("user_id") or payload.get("user_id") or "anonymous",
            "emotion": payload.get("emotion"),
            "language": payload.get("language"),
            "query": payload.get("query"),
            "query_seed": payload.get("query_seed"),
            "dynamic_profile": payload.get("dynamic_profile"),
            "cache": payload.get("cache"),
            "track_ids": payload.get("track_ids") or [],
            "provider": payload.get("provider"),
            "occurred_at": event.get("occurred_at"),
            "ingested_at": self._now(),
            "correlation_id": event.get("correlation_id"),
        }

    def _playback_history_document(self, event, payload):
        return {
            "event_id": event.get("event_id"),
            "user_id": event.get("user_id") or payload.get("user_id") or "anonymous",
            "action": payload.get("event_type"),
            "track_id": payload.get("track_id"),
            "emotion": payload.get("emotion"),
            "provider": payload.get("provider"),
            "occurred_at": event.get("occurred_at"),
            "ingested_at": self._now(),
            "correlation_id": event.get("correlation_id"),
        }

    def _normalize_event(self, event):
        if isinstance(event, bytes):
            event = event.decode("utf-8")

        if isinstance(event, str):
            event = json.loads(event)

        if not isinstance(event, dict):
            raise ValueError("Analytics event payload must be a JSON object.")

        if "event_id" not in event or "event_type" not in event:
            raise ValueError("Analytics event must include event_id and event_type.")

        return event

    def _now(self):
        return datetime.now(timezone.utc)
