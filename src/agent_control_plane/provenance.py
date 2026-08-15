"""Minimal structured provenance events for control-plane execution."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ProvenanceEvent:
    event: str
    task_id: str
    capability: Optional[str] = None
    state: Optional[str] = None
    detail: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def event_now(event: str, task_id: str, **kwargs: Any) -> ProvenanceEvent:
    return ProvenanceEvent(
        event=event,
        task_id=task_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        **kwargs,
    )
