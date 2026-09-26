import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.supervisor_service import SupervisorStopReason
from agent_control_plane.supervisor_service_host import (
    SupervisorServiceHostEvent,
    SupervisorServiceHostEventLatch,
)


def test_service_stop_maps_to_typed_stop_reason():
    latch = SupervisorServiceHostEventLatch()
    snapshot = latch.request(SupervisorServiceHostEvent.STOP)
    assert snapshot.event is SupervisorServiceHostEvent.STOP
    assert snapshot.stop_reason is SupervisorStopReason.SERVICE_STOP


def test_service_shutdown_maps_to_typed_stop_reason():
    latch = SupervisorServiceHostEventLatch()
    snapshot = latch.request(SupervisorServiceHostEvent.SHUTDOWN)
    assert snapshot.stop_reason is SupervisorStopReason.SERVICE_SHUTDOWN


def test_first_host_event_is_latched_idempotently():
    latch = SupervisorServiceHostEventLatch()
    first = latch.request(SupervisorServiceHostEvent.STOP)
    second = latch.request(SupervisorServiceHostEvent.SHUTDOWN)
    assert first.stop_reason is SupervisorStopReason.SERVICE_STOP
    assert second.stop_reason is SupervisorStopReason.SERVICE_STOP


def test_unknown_host_event_fails_closed():
    latch = SupervisorServiceHostEventLatch()
    with pytest.raises(AuthorityValidationError):
        latch.request("pause")
