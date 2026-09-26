"""Validate an external execution receipt against caller-supplied expectations."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.remote_execution_adapter import (
    RemoteExecutionReceipt,
    RemoteExecutionRequest,
    action_sha256,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--device-fingerprint", required=True)
    parser.add_argument("--device-attestation-level", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--side-effect-class", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--command", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    data = json.loads(Path(args.receipt).read_text(encoding="utf-8-sig"))
    request = RemoteExecutionRequest(
        request_id=args.request_id,
        device_id=args.device,
        expected_device_identity_fingerprint=args.device_fingerprint,
        expected_device_attestation_level=args.device_attestation_level,
        execution_profile=args.profile,
        expected_side_effect_class=args.side_effect_class,
        working_directory=args.cwd,
        command_or_action=args.command,
        action_sha256=action_sha256(args.command),
    )
    receipt = RemoteExecutionReceipt.from_mapping(data)
    receipt.assert_matches(request)
    if args.profile == "READ_ONLY_DISCOVERY":
        receipt.assert_read_only()
    else:
        receipt.assert_completed()
    print("REMOTE_EXECUTION_RECEIPT=PASS")
    print(f"REQUEST_ID={receipt.request_id}")
    print(f"DEVICE={receipt.device_id}")
    print(f"PROFILE={receipt.execution_profile}")
    print(f"ACTION_SHA256={receipt.action_sha256}")
    print(f"FILES_CHANGED={len(receipt.files_changed)}")


if __name__ == "__main__":
    main()
