import asyncio
import json

from config import get_analytics_settings, get_event_settings
from services.analytics.repository import MongoAnalyticsRepository
from services.analytics.service import AnalyticsService
from services.events import EVENT_TOPICS


class AnalyticsEventConsumer:
    def __init__(self, service, event_settings):
        self.service = service
        self.event_settings = event_settings
        self.topics = tuple(EVENT_TOPICS.values())

    async def handle_event(self, event):
        return await self.service.handle_event(event)

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
            client_id=f"{self.event_settings.kafka_client_id}-analytics-consumer",
            group_id=f"{self.event_settings.kafka_consumer_group_id}-analytics",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=self._deserialize_value,
        )

        try:
            await self.service.ensure_ready()
            print(
                "Starting analytics Kafka consumer "
                f"bootstrap={self.event_settings.kafka_bootstrap_servers}",
                flush=True,
            )
            await consumer.start()
            print(
                "Analytics Kafka consumer subscribed to " + ", ".join(self.topics),
                flush=True,
            )
            async for message in consumer:
                result = await self.handle_event(message.value)
                print(
                    f"Stored analytics event {result.get('event_type')}: {result}",
                    flush=True,
                )
        finally:
            print("Stopping analytics Kafka consumer.", flush=True)
            await consumer.stop()

    def _deserialize_value(self, value):
        if isinstance(value, bytes):
            value = value.decode("utf-8")

        if isinstance(value, str):
            return json.loads(value)

        return value


def create_analytics_event_consumer():
    analytics_settings = get_analytics_settings()

    try:
        repository = MongoAnalyticsRepository(analytics_settings)
    except RuntimeError as exc:
        if analytics_settings.fail_open:
            return DisabledAnalyticsEventConsumer(str(exc))

        raise

    return AnalyticsEventConsumer(
        AnalyticsService(repository, analytics_settings),
        get_event_settings(),
    )


class DisabledAnalyticsEventConsumer:
    def __init__(self, reason):
        self.reason = reason

    async def consume_forever(self):
        return {
            "status": "disabled",
            "reason": self.reason,
        }


async def main():
    consumer = create_analytics_event_consumer()
    result = await consumer.consume_forever()

    if result:
        print(result, flush=True)

    return result


if __name__ == "__main__":
    asyncio.run(main())
