#!/usr/bin/env python3
"""Record one CEP paired-task adjudication from externally produced observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

from agent_control_plane.context_baseline import (
    baseline_observation_from_mapping,
    baseline_observation_sha256,
)
from agent_control_plane.context_live_pair import (
    PairedTaskObservation,
    evaluate_paired_task,
)
from agent_control_plane.context_state import context_state_from_mapping


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Adjudicate externally produced CEP control/treatment observations "
            "without selecting, invoking, or authorizing tools."
        )
    )
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--model-identity", required=True)
    parser.add_argument("--config-identity", required=True)
    parser.add_argument("--primary-metric", required=True)
    parser.add_argument("--control-context-state", required=True)
    parser.add_argument("--control-observation", required=True)
    parser.add_argument("--treatment-context-state", required=True)
    parser.add_argument("--treatment-observation", required=True)
    parser.add_argument("--output", required=True)
    return parser


def _load_observation(
    observation_path: Path,
    context_state_path: Path,
):
    envelope = json.loads(observation_path.read_text(encoding="utf-8"))
    if not isinstance(envelope, Mapping):
        raise TypeError("observation envelope must be a mapping")
    if set(envelope) != {"observation_sha256", "observation"}:
        raise ValueError("observation envelope fields mismatch")
    raw_observation = envelope["observation"]
    if not isinstance(raw_observation, Mapping):
        raise TypeError("observation must be a mapping")

    raw_state = json.loads(context_state_path.read_text(encoding="utf-8"))
    state = context_state_from_mapping(raw_state)
    observation = baseline_observation_from_mapping(
        raw_observation,
        context_state=state,
    )
    if envelope["observation_sha256"] != baseline_observation_sha256(observation):
        raise ValueError("observation envelope identity mismatch")
    return observation


def main() -> int:
    args = _parser().parse_args()
    control = _load_observation(
        Path(args.control_observation),
        Path(args.control_context_state),
    )
    treatment = _load_observation(
        Path(args.treatment_observation),
        Path(args.treatment_context_state),
    )
    pair = PairedTaskObservation(
        pair_id=args.pair_id,
        model_identity=args.model_identity,
        config_identity=args.config_identity,
        control=control,
        treatment=treatment,
        primary_metric=args.primary_metric,
    )
    result = evaluate_paired_task(pair)
    Path(args.output).write_text(
        json.dumps(
            result,
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
