import json
from pathlib import Path

import pytest

from agent_control_plane.contract.model import ContractValidationError
from agent_control_plane.remote_execution_adapter import (
    RemoteExecutionReceipt,
    RemoteExecutionRequest,
    action_sha256,
)


def request(command="git status --short"):
    return RemoteExecutionRequest(
        request_id="req-1",
        device_id="test-device",
        expected_device_identity_fingerprint="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        expected_device_attestation_level="SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED",
        execution_profile="READ_ONLY_DISCOVERY",
        expected_side_effect_class="READ_ONLY",
        working_directory=r"C:\repo",
        command_or_action=command,
        action_sha256=action_sha256(command),
    )


def receipt_data(command="git status --short"):
    return {
        "request_id": "req-1",
        "device": "test-device",
        "device_identity_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "device_attestation_level": "SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED",
        "execution_profile": "READ_ONLY_DISCOVERY",
        "side_effect_class": "READ_ONLY",
        "working_directory": r"C:\repo",
        "command_or_action": command,
        "action_sha256": action_sha256(command),
        "exit_code": 0,
        "sequence_number": 1,
        "previous_receipt_sha256": None,
        "clock_rollback_detected": False,
        "trusted_time_established": False,
        "files_changed": [],
        "artifacts": [],
        "side_effects": [],
        "not_established": ["independent_validation"],
        "postconditions": {
            "command_completed": True,
            "working_tree_unchanged": True,
        },
    }


def test_matching_read_only_receipt_is_accepted():
    req = request()
    receipt = RemoteExecutionReceipt.from_mapping(receipt_data())
    receipt.assert_matches(req)
    receipt.assert_read_only()


def test_action_digest_mismatch_fails_closed():
    data = receipt_data()
    data["command_or_action"] = "git clean -fd"
    with pytest.raises(ContractValidationError, match="digest mismatch"):
        RemoteExecutionReceipt.from_mapping(data)


def test_device_drift_fails_closed():
    req = request()
    data = receipt_data()
    data["device"] = "other-host"
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="device_id mismatch"):
        receipt.assert_matches(req)
def test_read_only_side_effect_fails_closed():
    data = receipt_data()
    data["files_changed"] = ["unexpected.txt"]
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="changed files"):
        receipt.assert_read_only()


def test_nonzero_exit_is_not_completion():
    data = receipt_data()
    data["exit_code"] = 1
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="exit successfully"):
        receipt.assert_completed()


def test_real_control_receipt_when_supplied(tmp_path):
    marker = Path(__file__).parent / "fixtures" / "remote-execution-receipt.json"
    if not marker.exists():
        pytest.skip("no external receipt fixture supplied")
    receipt = RemoteExecutionReceipt.from_mapping(json.loads(marker.read_text()))
    receipt.assert_read_only()


from agent_control_plane.remote_execution_adapter import (
    RemoteExecutionFreshness,
    RemoteExecutionReplayGuard,
    assert_known_success,
    classify_remote_outcome,
)


def test_freshness_accepts_bounded_window_and_rejects_expiry():
    freshness = RemoteExecutionFreshness(
        nonce="nonce-1",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=110,
    )
    freshness.assert_fresh(now_epoch_seconds=105)
    with pytest.raises(ContractValidationError, match="expired"):
        freshness.assert_fresh(now_epoch_seconds=111)


def test_replay_guard_is_single_use_for_request_and_nonce():
    guard = RemoteExecutionReplayGuard()
    req = request()
    freshness = RemoteExecutionFreshness(
        nonce="nonce-1",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=110,
    )
    guard.consume(req, freshness, now_epoch_seconds=105)
    with pytest.raises(ContractValidationError, match="replay detected"):
        guard.consume(req, freshness, now_epoch_seconds=106)


def test_unknown_completion_is_fail_closed():
    data = receipt_data()
    data["postconditions"] = {}
    receipt = RemoteExecutionReceipt.from_mapping(data)
    assert classify_remote_outcome(receipt) == "UNKNOWN"
    with pytest.raises(ContractValidationError, match="UNKNOWN"):
        assert_known_success(receipt)


def test_nonzero_exit_is_explicit_failed_outcome():
    data = receipt_data()
    data["exit_code"] = 7
    receipt = RemoteExecutionReceipt.from_mapping(data)
    assert classify_remote_outcome(receipt) == "FAILED"
    with pytest.raises(ContractValidationError, match="FAILED"):
        assert_known_success(receipt)


from agent_control_plane.remote_execution_adapter import (
    DurableRemoteExecutionReplayGuard,
)


def test_durable_replay_guard_survives_reopen(tmp_path):
    db = tmp_path / "replay.sqlite3"
    req = request()
    freshness = RemoteExecutionFreshness(
        nonce="durable-nonce",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=110,
    )
    DurableRemoteExecutionReplayGuard(db).consume(
        req, freshness, now_epoch_seconds=105
    )
    reopened = DurableRemoteExecutionReplayGuard(db)
    with pytest.raises(ContractValidationError, match="replay detected"):
        reopened.consume(req, freshness, now_epoch_seconds=106)


def test_read_only_side_effect_class_mismatch_fails_closed():
    data = receipt_data()
    data["side_effect_class"] = "TEST_SIDE_EFFECTS"
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="side-effect class mismatch"):
        receipt.assert_read_only()


from agent_control_plane.remote_execution_adapter import (
    sign_request_hmac_sha256,
    verify_request_hmac_sha256,
    sign_receipt_hmac_sha256,
    verify_receipt_hmac_sha256,
)


def test_request_hmac_binds_action_and_freshness():
    req = request()
    freshness = RemoteExecutionFreshness(
        nonce="nonce-sign",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=110,
    )
    key = b"test-only-key-that-is-long-enough-32"
    signature = sign_request_hmac_sha256(req, freshness, key=key)
    verify_request_hmac_sha256(req, freshness, key=key, signature=signature)
    changed = request(command="git clean -fd")
    with pytest.raises(ContractValidationError, match="signature mismatch"):
        verify_request_hmac_sha256(changed, freshness, key=key, signature=signature)


def test_request_hmac_rejects_freshness_drift():
    req = request()
    first = RemoteExecutionFreshness(
        nonce="nonce-sign",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=110,
    )
    second = RemoteExecutionFreshness(
        nonce="nonce-sign",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=111,
    )
    key = b"test-only-key-that-is-long-enough-32"
    signature = sign_request_hmac_sha256(req, first, key=key)
    with pytest.raises(ContractValidationError, match="signature mismatch"):
        verify_request_hmac_sha256(req, second, key=key, signature=signature)


def test_receipt_hmac_detects_side_effect_class_tamper():
    key = b"test-only-key-that-is-long-enough-32"
    receipt = RemoteExecutionReceipt.from_mapping(receipt_data())
    signature = sign_receipt_hmac_sha256(receipt, key=key)
    verify_receipt_hmac_sha256(receipt, key=key, signature=signature)
    tampered = receipt_data()
    tampered["side_effect_class"] = "TEST_SIDE_EFFECTS"
    tampered_receipt = RemoteExecutionReceipt.from_mapping(tampered)
    with pytest.raises(ContractValidationError, match="signature mismatch"):
        verify_receipt_hmac_sha256(tampered_receipt, key=key, signature=signature)


from agent_control_plane.remote_execution_adapter import (
    verify_detached_receipt_file_hmac,
)


def test_detached_receipt_file_hmac_detects_any_byte_tamper(tmp_path):
    receipt = tmp_path / "receipt.json"
    signature = tmp_path / "receipt.json.hmac-sha256"
    key = b"test-only-key-that-is-long-enough-32"
    receipt.write_bytes(b'{"status":"ok"}\n')
    import hashlib as _hashlib
    import hmac as _hmac
    signature.write_text(
        _hmac.new(key, receipt.read_bytes(), _hashlib.sha256).hexdigest() + "\n",
        encoding="ascii",
    )
    verify_detached_receipt_file_hmac(receipt, signature, key=key)
    receipt.write_bytes(b'{"status":"tampered"}\n')
    with pytest.raises(ContractValidationError, match="signature mismatch"):
        verify_detached_receipt_file_hmac(receipt, signature, key=key)


from agent_control_plane.remote_execution_adapter import (
    verify_receipt_signature_envelope,
)


def test_signature_envelope_binds_key_id_and_receipt_bytes(tmp_path):
    import hashlib as _hashlib
    import hmac as _hmac
    import json as _json

    key = b"test-only-key-that-is-long-enough-32"
    receipt = tmp_path / "receipt.json"
    envelope = tmp_path / "receipt.json.signature.json"
    receipt.write_bytes(b'{"status":"ok"}\n')
    body = receipt.read_bytes()
    envelope.write_text(
        _json.dumps(
            {
                "schema_version": "ndr.receipt-signature.v1",
                "algorithm": "HMAC-SHA256",
                "key_id": _hashlib.sha256(key).hexdigest()[:16],
                "receipt_sha256": _hashlib.sha256(body).hexdigest(),
                "signature": _hmac.new(key, body, _hashlib.sha256).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    verify_receipt_signature_envelope(receipt, envelope, key=key)
    receipt.write_bytes(b'{"status":"changed"}\n')
    with pytest.raises(ContractValidationError, match="receipt sha256 mismatch"):
        verify_receipt_signature_envelope(receipt, envelope, key=key)


def test_freshness_ttl_is_capped():
    with pytest.raises(ContractValidationError, match="ttl exceeds maximum"):
        RemoteExecutionFreshness(
            nonce="too-long",
            issued_at_epoch_seconds=100,
            expires_at_epoch_seconds=401,
        )


def test_receipt_side_effect_class_must_match_request():
    req = request()
    data = receipt_data()
    data["side_effect_class"] = "TEST_SIDE_EFFECTS"
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="side_effect_class mismatch"):
        receipt.assert_matches(req)


def test_device_fingerprint_drift_fails_closed():
    req = request()
    data = receipt_data()
    data["device_identity_fingerprint"] = "0" * 64
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="device_identity_fingerprint mismatch"):
        receipt.assert_matches(req)


def test_attestation_level_drift_fails_closed():
    req = request()
    data = receipt_data()
    data["device_attestation_level"] = "HARDWARE_ATTESTED"
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="device_attestation_level mismatch"):
        receipt.assert_matches(req)


def test_clock_rollback_fails_read_only_validation():
    data = receipt_data()
    data["clock_rollback_detected"] = True
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="clock rollback detected"):
        receipt.assert_read_only()


def test_sequence_number_must_be_positive():
    data = receipt_data()
    data["sequence_number"] = 0
    with pytest.raises(ContractValidationError, match="positive integer"):
        RemoteExecutionReceipt.from_mapping(data)


def test_trusted_time_is_not_inferred_from_local_sequence():
    data = receipt_data()
    receipt = RemoteExecutionReceipt.from_mapping(data)
    assert receipt.trusted_time_established is False
    receipt.assert_read_only()


def test_previous_receipt_hash_must_be_sha256_when_present():
    data = receipt_data()
    data["previous_receipt_sha256"] = "not-a-digest"
    with pytest.raises(ContractValidationError, match="previous_receipt_sha256"):
        RemoteExecutionReceipt.from_mapping(data)


def test_read_only_reported_side_effect_fails_closed():
    data = receipt_data()
    data["side_effects"] = [{"kind": "network", "target": "example.invalid"}]
    receipt = RemoteExecutionReceipt.from_mapping(data)
    with pytest.raises(ContractValidationError, match="reported side effects"):
        receipt.assert_read_only()


from agent_control_plane.remote_execution_adapter import verify_receipt_chain_link


def test_receipt_chain_link_verifies_hash_and_sequence(tmp_path):
    previous = receipt_data()
    previous["sequence_number"] = 10
    current = receipt_data()
    current["request_id"] = "req-2"
    current["sequence_number"] = 11

    previous_path = tmp_path / "previous.json"
    current_path = tmp_path / "current.json"

    previous_path.write_text(json.dumps(previous), encoding="utf-8")
    import hashlib as _hashlib
    current["previous_receipt_sha256"] = _hashlib.sha256(
        previous_path.read_bytes()
    ).hexdigest()
    current_path.write_text(json.dumps(current), encoding="utf-8")

    verify_receipt_chain_link(previous_path, current_path)


def test_receipt_chain_link_rejects_noncontiguous_sequence(tmp_path):
    previous = receipt_data()
    previous["sequence_number"] = 10
    current = receipt_data()
    current["request_id"] = "req-2"
    current["sequence_number"] = 12

    previous_path = tmp_path / "previous.json"
    current_path = tmp_path / "current.json"

    previous_path.write_text(json.dumps(previous), encoding="utf-8")
    import hashlib as _hashlib
    current["previous_receipt_sha256"] = _hashlib.sha256(
        previous_path.read_bytes()
    ).hexdigest()
    current_path.write_text(json.dumps(current), encoding="utf-8")

    with pytest.raises(ContractValidationError, match="sequence is not contiguous"):
        verify_receipt_chain_link(previous_path, current_path)


def test_hmac_helpers_reject_short_keys():
    req = request()
    freshness = RemoteExecutionFreshness(
        nonce="nonce-short-key",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=110,
    )
    with pytest.raises(ContractValidationError, match="at least 32 bytes"):
        sign_request_hmac_sha256(req, freshness, key=b"short")
    receipt = RemoteExecutionReceipt.from_mapping(receipt_data())
    with pytest.raises(ContractValidationError, match="at least 32 bytes"):
        sign_receipt_hmac_sha256(receipt, key=b"short")


from agent_control_plane.remote_execution_adapter import (
    assert_read_only_command_allowed,
)


@pytest.mark.parametrize(
    "command",
    [
        "Remove-Item -Recurse -Force C:\\important",
        "git status --short; Remove-Item victim.txt",
        "git status --short | Set-Content victim.txt",
        "git status --short && del victim.txt",
        "Write-Output SIGNED_E2E_OK",
    ],
)
def test_signed_read_only_policy_rejects_arbitrary_or_chained_commands(command):
    with pytest.raises(ContractValidationError, match="not in signed read-only allowlist"):
        assert_read_only_command_allowed(command)


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git status --porcelain=v1",
        "git rev-parse HEAD",
        "git branch --show-current",
        "git remote get-url origin",
        "git diff --name-only",
        "git diff --cached --check",
    ],
)
def test_signed_read_only_policy_accepts_only_pre_reviewed_commands(command):
    assert_read_only_command_allowed(command)


def test_receipt_accepts_canonical_device_id_field():
    data = receipt_data()
    data["device_id"] = data.pop("device")
    receipt = RemoteExecutionReceipt.from_mapping(data)
    assert receipt.device_id == "test-device"


def test_receipt_legacy_device_alias_remains_supported():
    receipt = RemoteExecutionReceipt.from_mapping(receipt_data())
    assert receipt.device_id == "test-device"
