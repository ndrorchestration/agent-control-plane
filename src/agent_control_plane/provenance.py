"""Structured provenance events for control-plane execution."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ProvenanceEvent:
    event: str
    task_id: str
    run_id: str
    capability: Optional[str] = None
    state: Optional[str] = None
    detail: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def event_now(event: str, task_id: str, run_id: str, **kwargs: Any) -> ProvenanceEvent:
    if not run_id.strip():
        raise ValueError("run_id must not be empty")
    return ProvenanceEvent(
        event=event,
        task_id=task_id,
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        **kwargs,
    )
