from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class EventEnvelope:
    event_type: str
    source_service: str
    payload: dict
    user_id: str | None = None
    correlation_id: str | None = None
    schema_version: int = 1
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "source_service": self.source_service,
            "payload": self.payload,
        }
