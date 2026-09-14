"""Explicit mapping from legacy ACP provenance into the execution contract."""

from typing import Iterable, Optional

from ..provenance import ProvenanceEvent
from .model import (
    ArtifactRef,
    ComponentIdentity,
    ContractValidationError,
    ExecutionEvent,
    ExecutionIdentity,
    TraceContext,
)


def map_provenance_event(
    event: ProvenanceEvent,
    *,
    identity: ExecutionIdentity,
    trace: TraceContext,
    component: ComponentIdentity,
    monotonic_ns: int,
    input_artifacts: Iterable[ArtifactRef] = (),
    output_artifacts: Iterable[ArtifactRef] = (),
    policy_decision_ref: Optional[str] = None,
) -> ExecutionEvent:
    """Convert one legacy provenance event without fabricating missing context."""
    if event.run_id != identity.run_id:
        raise ContractValidationError(
            f"provenance run_id {event.run_id!r} does not match contract run_id {identity.run_id!r}"
        )

    return ExecutionEvent(
        event_type=event.event,
        identity=identity,
        trace=trace,
        component=component,
        task_id=event.task_id,
        status=event.state if event.state is not None else "unspecified",
        utc_timestamp=event.timestamp,
        monotonic_ns=monotonic_ns,
        capability=event.capability,
        policy_decision_ref=policy_decision_ref,
        input_artifacts=tuple(input_artifacts),
        output_artifacts=tuple(output_artifacts),
        detail=event.detail,
    )
