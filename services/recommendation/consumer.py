import asyncio
import json

from config import get_event_settings, get_recommendation_settings
from services.events import EVENT_TOPICS, create_event_producer
from services.recommendation.cache import RecommendationCache
from services.recommendation.jamendo_client import JamendoClient
from services.recommendation.service import RecommendationService


class RecommendationEventConsumer:
    def __init__(self, service, event_settings):
        self.service = service
        self.event_settings = event_settings
        self.topics = (
            EVENT_TOPICS["emotion.detected"],
            EVENT_TOPICS["playback.event"],
        )

    async def handle_event(self, event):
        normalized_event = self._normalize_event(event)
        event_type = normalized_event.get("event_type")

        if event_type == "emotion.detected":
            return await self.service.handle_emotion_detected_event(
                normalized_event,
                precompute=self.event_settings.recommendation_precompute_enabled,
            )

        if event_type == "playback.event":
            return await self.service.handle_playback_event(normalized_event)

        return {
            "status": "skipped",
            "reason": f"Unsupported event type: {event_type}",
        }

    async def consume_forever(self):
        if not self.event_settings.kafka_enabled:
            return {
                "status": "disabled",
                "reason": "Kafka eventing is disabled.",
            }

        try:
            from aiokafka import AIOKafkaConsumer
        except ImportError as exc:
            if self.event_settings.kafka_fail_open:
                return {
                    "status": "disabled",
                    "reason": "Kafka dependency is not installed.",
                }

            raise RuntimeError(
                "Kafka dependency is not installed. Run `python -m pip install -r requirements.txt`."
            ) from exc

        consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=self.event_settings.kafka_bootstrap_servers,
            client_id=f"{self.event_settings.kafka_client_id}-recommendation-consumer",
            group_id=self.event_settings.kafka_consumer_group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=self._deserialize_value,
        )

        try:
            print(
                "Starting recommendation Kafka consumer "
                f"bootstrap={self.event_settings.kafka_bootstrap_servers} "
                f"group={self.event_settings.kafka_consumer_group_id}",
                flush=True,
            )
            await consumer.start()
            print(
                "Recommendation Kafka consumer subscribed to "
                + ", ".join(self.topics),
                flush=True,
            )
            async for message in consumer:
                result = await self.handle_event(message.value)
                event_type = (
                    message.value.get("event_type")
                    if isinstance(message.value, dict)
                    else "unknown"
                )
                print(
                    f"Handled Kafka event {event_type}: {result}",
                    flush=True,
                )
        finally:
            print("Stopping recommendation Kafka consumer.", flush=True)
            await consumer.stop()

    def _normalize_event(self, event):
        if isinstance(event, bytes):
            event = self._deserialize_value(event)

        if isinstance(event, str):
            event = json.loads(event)

        if not isinstance(event, dict):
            raise ValueError("Kafka event payload must be a JSON object.")

        return event

    def _deserialize_value(self, value):
        if isinstance(value, bytes):
            value = value.decode("utf-8")

        if isinstance(value, str):
            return json.loads(value)

        return value


def create_recommendation_event_consumer():
    recommendation_settings = get_recommendation_settings()
    event_settings = get_event_settings()
    service = RecommendationService(
        JamendoClient(recommendation_settings),
        recommendation_settings,
        cache=RecommendationCache(
            recommendation_settings.redis_url,
            namespace=recommendation_settings.redis_namespace,
            fail_open=recommendation_settings.redis_fail_open,
        ),
        event_producer=create_event_producer(event_settings),
    )
    return RecommendationEventConsumer(service, event_settings)


async def main():
    consumer = create_recommendation_event_consumer()
    result = await consumer.consume_forever()

    if result:
        print(result, flush=True)

    return result


if __name__ == "__main__":
    asyncio.run(main())
