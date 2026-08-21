import asyncio
from dataclasses import replace

import pytest

from config import EventSettings, get_event_settings
from services.events import EVENT_TOPICS, EventEnvelope, NoopEventProducer, create_event_producer
from services.events.producer import KafkaEventProducer, topic_for_event_type


def test_event_topics_include_phase_two_topics():
    assert EVENT_TOPICS == {
        "camera.capture": "camera.capture.v1",
        "emotion.detected": "emotion.detected.v1",
        "recommendation.requested": "recommendation.requested.v1",
        "recommendation.generated": "recommendation.generated.v1",
        "recommendation.served": "recommendation.served.v1",
        "playback.event": "playback.event.v1",
    }


def test_event_envelope_shape():
    envelope = EventEnvelope(
        event_type="emotion.detected",
        source_service="emotion-api",
        user_id="user-123",
        correlation_id="request-123",
        payload={"emotion": "Happy", "confidence": 0.87},
    )

    payload = envelope.to_dict()

    assert payload["event_id"]
    assert payload["event_type"] == "emotion.detected"
    assert payload["schema_version"] == 1
    assert payload["occurred_at"].endswith("Z")
    assert payload["user_id"] == "user-123"
    assert payload["correlation_id"] == "request-123"
    assert payload["source_service"] == "emotion-api"
    assert payload["payload"] == {"emotion": "Happy", "confidence": 0.87}


def test_noop_producer_records_events_without_kafka():
    async def run():
        producer = NoopEventProducer()
        result = await producer.publish(
            EventEnvelope(
                event_type="playback.event",
                source_service="api-gateway",
                user_id="user-123",
                payload={"event_type": "started", "track_id": "track-1"},
            )
        )

        assert result["noop"] is True
        assert result["topic"] == "playback.event.v1"
        assert producer.published == [result]

    asyncio.run(run())


def test_create_event_producer_defaults_to_noop_when_kafka_disabled():
    settings = replace(get_event_settings(), kafka_enabled=False)

    assert isinstance(create_event_producer(settings), NoopEventProducer)


def test_create_event_producer_uses_noop_when_enabled_without_bootstrap_and_fail_open():
    settings = EventSettings(
        kafka_enabled=True,
        kafka_bootstrap_servers=None,
        kafka_client_id="test-client",
        kafka_fail_open=True,
    )

    assert isinstance(create_event_producer(settings), NoopEventProducer)


def test_create_event_producer_uses_kafka_when_enabled_and_configured():
    settings = EventSettings(
        kafka_enabled=True,
        kafka_bootstrap_servers="127.0.0.1:9092",
        kafka_client_id="test-client",
        kafka_fail_open=True,
    )

    assert isinstance(create_event_producer(settings), KafkaEventProducer)


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValueError, match="Unsupported event type"):
        topic_for_event_type("unknown.event")
