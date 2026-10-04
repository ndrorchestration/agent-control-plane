#!/usr/bin/env python3
"""Record one explicit CEP baseline observation from operator-supplied JSON/counts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_control_plane.context_baseline import (
    BaselineObservation,
    baseline_observation_envelope,
)
from agent_control_plane.context_metrics import ContextTelemetry
from agent_control_plane.context_state import context_state_from_mapping


_COUNT_FIELDS = (
    "input_tokens",
    "output_tokens",
    "tool_result_tokens",
    "tool_definitions_exposed",
    "tools_invoked",
    "retrieved_tokens",
    "used_retrieved_tokens",
    "retrieved_items",
    "cacheable_prefix_tokens",
    "novel_prefix_tokens",
    "decision_relevant_input_tokens",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record an explicit CEP baseline observation without estimating missing values."
    )
    parser.add_argument("--context-state", required=True, help="ContextState JSON file")
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--task-contract", required=True)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--acceptance", required=True)
    parser.add_argument("--notes")
    parser.add_argument("--output", required=True)
    for field in _COUNT_FIELDS:
        parser.add_argument(f"--{field.replace('_', '-')}", type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    state_payload = json.loads(Path(args.context_state).read_text(encoding="utf-8"))
    state = context_state_from_mapping(state_payload)

    telemetry = ContextTelemetry(
        **{field: getattr(args, field) for field in _COUNT_FIELDS}
    )
    observation = BaselineObservation(
        observation_id=args.observation_id,
        task_contract=args.task_contract,
        context_state=state,
        telemetry=telemetry,
        outcome=args.outcome,
        acceptance=args.acceptance,
        notes=args.notes,
    )
    output = Path(args.output)
    output.write_text(
        json.dumps(
            baseline_observation_envelope(observation),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
