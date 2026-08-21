import json

from services.events.envelope import EventEnvelope
from services.events.topics import EVENT_TOPICS


class EventPublishError(RuntimeError):
    pass


class NoopEventProducer:
    def __init__(self, reason="Kafka eventing is disabled."):
        self.reason = reason
        self.published = []

    async def start(self):
        return None

    async def stop(self):
        return None

    async def publish(self, event, topic=None):
        envelope = _coerce_envelope(event)
        resolved_topic = topic or topic_for_event_type(envelope.event_type)
        record = {"topic": resolved_topic, "event": envelope.to_dict(), "noop": True}
        self.published.append(record)
        return record


class KafkaEventProducer:
    def __init__(self, settings):
        self.settings = settings
        self._producer = None

    async def start(self):
        if self._producer:
            return None

        if not self.settings.kafka_bootstrap_servers:
            raise EventPublishError("KAFKA_BOOTSTRAP_SERVERS is not configured.")

        try:
            from aiokafka import AIOKafkaProducer
        except ImportError as exc:
            raise EventPublishError(
                "Kafka dependency is not installed. Run `python -m pip install -r requirements.txt`."
            ) from exc

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            client_id=self.settings.kafka_client_id,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        )
        await self._producer.start()
        return None

    async def stop(self):
        if not self._producer:
            return None

        await self._producer.stop()
        self._producer = None
        return None

    async def publish(self, event, topic=None):
        envelope = _coerce_envelope(event)
        resolved_topic = topic or topic_for_event_type(envelope.event_type)

        try:
            await self.start()
            await self._producer.send_and_wait(resolved_topic, envelope.to_dict())
        except Exception as exc:
            if self.settings.kafka_fail_open:
                return {
                    "topic": resolved_topic,
                    "event": envelope.to_dict(),
                    "published": False,
                    "fail_open": True,
                    "detail": str(exc) or exc.__class__.__name__,
                }

            raise

        return {
            "topic": resolved_topic,
            "event": envelope.to_dict(),
            "published": True,
            "fail_open": False,
        }


def create_event_producer(settings):
    if not settings.kafka_enabled:
        return NoopEventProducer()

    if not settings.kafka_bootstrap_servers and settings.kafka_fail_open:
        return NoopEventProducer("KAFKA_BOOTSTRAP_SERVERS is not configured.")

    return KafkaEventProducer(settings)


def topic_for_event_type(event_type):
    try:
        return EVENT_TOPICS[event_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported event type: {event_type}") from exc


def _coerce_envelope(event):
    if isinstance(event, EventEnvelope):
        return event

    if isinstance(event, dict):
        return EventEnvelope(**event)

    raise TypeError("event must be an EventEnvelope or dict.")
