import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.supervisor_concurrency import (
    SupervisorConcurrencyPolicy,
    SupervisorWorkerSchedulingMode,
)


def test_default_policy_is_serial_contract_order():
    policy = SupervisorConcurrencyPolicy()
    assert policy.max_in_flight_workers == 1
    assert (
        policy.scheduling_mode
        is SupervisorWorkerSchedulingMode.CONTRACT_ORDER_SERIAL
    )
    workers = ("relay-a", "relay-b", "relay-c")
    assert policy.ordered(workers) == workers


def test_parallelism_above_one_fails_closed():
    with pytest.raises(
        AuthorityValidationError,
        match="parallel supervisor worker scheduling is not authorized",
    ):
        SupervisorConcurrencyPolicy(max_in_flight_workers=2)


def test_invalid_zero_concurrency_fails_closed():
    with pytest.raises(
        AuthorityValidationError,
        match="must be an integer >= 1",
    ):
        SupervisorConcurrencyPolicy(max_in_flight_workers=0)
