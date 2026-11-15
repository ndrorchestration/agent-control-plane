"""Source-locked Python consumer of the same golden interop vectors as Node.js."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from agent_control_plane.contract import ContractValidationError, ExecutionEvent
from integration.execution_v1_interop import (
    from_cloudevent,
    to_cloudevent,
    to_otel_trace_context,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads(
    (ROOT / "fixtures/execution_v1/interop_cases.json").read_text(encoding="utf-8")
)
SCHEMA = json.loads((ROOT / "contracts/execution.v1.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
CASES = {case["name"]: case for case in FIXTURES["cases"]}


def _mutated(value, instruction):
    result = deepcopy(value)
    node = result
    for key in instruction["path"][:-1]:
        node = node[key]
    key = instruction["path"][-1]
    if instruction.get("remove", False):
        del node[key]
    else:
        node[key] = instruction["value"]
    return result


def test_interop_profile_identity_is_explicit():
    assert FIXTURES["profile"] == "acp.execution.v1.interop-fixtures.v1"
    assert len(CASES) == len(FIXTURES["cases"])
    assert "Synthetic" in FIXTURES["claim_boundary"]


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda c: c["name"])
def test_python_matches_shared_golden_contract_and_cloud_events(case):
    assert VALIDATOR.is_valid(case["event"])
    native = ExecutionEvent.from_dict(case["event"])
    assert native.to_dict() == case["event"]
    envelope = to_cloudevent(native)
    assert envelope["id"] == case["expected"]["cloudevent_id"]
    assert envelope["source"] == case["expected"]["cloudevent_source"]
    assert envelope["data"] == case["event"]
    assert from_cloudevent(json.loads(json.dumps(envelope))) == native
    if case["expected"]["otel"] is None:
        with pytest.raises(ContractValidationError):
            to_otel_trace_context(native)
    else:
        assert to_otel_trace_context(native) == case["expected"]["otel"]


@pytest.mark.parametrize("instruction", FIXTURES["mutations"], ids=lambda c: c["name"])
def test_python_matches_shared_fail_closed_mutations(instruction):
    native = ExecutionEvent.from_dict(CASES[instruction["case"]]["event"])
    if instruction["target"] == "envelope":
        mutated = _mutated(to_cloudevent(native), instruction)
        with pytest.raises(ContractValidationError):
            from_cloudevent(mutated)
    else:
        mutated = _mutated(native.to_dict(), instruction)
        assert not VALIDATOR.is_valid(mutated)
        # The strict JSON Schema is the normative interop profile. ACP's native
        # from_dict intentionally predates it and may ignore unknown keys.


def test_receipt_is_observation_not_authorization():
    denied = ExecutionEvent.from_dict(CASES["denied-uri-escaping"]["event"])
    projected = to_cloudevent(denied)
    assert projected["data"]["status"] == "denied"
    assert projected["data"]["policy_decision_ref"] == "explicit-deny-18"
    assert "authorized" not in projected
