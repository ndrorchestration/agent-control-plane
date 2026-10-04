import json
import subprocess
import sys


def test_request_attestation_preflight_is_blocked_and_distinct() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/build_model_request_attestations.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)

    assert value["status"] == "BLOCKED_TRANSPORT_NOT_CONFIGURED"
    assert value["dynamic_exposure_observed"] is False

    control = value["control"]
    treatment = value["treatment"]

    assert control["manifest"]["tool_count"] == 89
    assert treatment["manifest"]["tool_count"] == 1
    assert control["manifest"]["catalog_sha256"] != treatment["manifest"]["catalog_sha256"]
    assert control["manifest"]["tool_payload_sha256"] != treatment["manifest"]["tool_payload_sha256"]
    assert control["transport_receipt"]["sent"] is False
    assert treatment["transport_receipt"]["sent"] is False
    assert control["transport_receipt"]["provider_request_id"] is None
    assert treatment["transport_receipt"]["provider_request_id"] is None
