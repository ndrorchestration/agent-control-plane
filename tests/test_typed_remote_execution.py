import hashlib
import json
from dataclasses import FrozenInstanceError
import subprocess
import sys
from pathlib import Path

import pytest

from agent_control_plane.contract.model import ContractValidationError
from agent_control_plane.remote_execution_adapter import (
    DurableRemoteExecutionReplayGuard,
    RemoteExecutionFreshness,
)
from agent_control_plane.typed_remote_execution import (
    GIT_READ_ONLY_PREFIX,
    READ_ONLY_OPERATION_SPECS,
    TypedRemoteExecutionRequest,
    TypedRemoteExecutionResult,
    canonical_typed_request_bytes,
    operation_sha256,
    render_read_only_operation_argv,
    resolve_authorized_working_directory,
    sign_typed_request_hmac_sha256,
    typed_request_envelope_from_mapping,
    typed_request_envelope_mapping,
    verify_typed_request_hmac_sha256,
)


FINGERPRINT = "a" * 64
KEY = b"typed-test-key-that-is-long-enough-32"


def typed_request(operation_id="git.status.short", parameters=None):
    if parameters is None:
        parameters = {}
    return TypedRemoteExecutionRequest(
        request_id="typed-req-1",
        device_id="test-device",
        expected_device_identity_fingerprint=FINGERPRINT,
        expected_device_attestation_level="SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED",
        execution_profile="READ_ONLY_DISCOVERY",
        expected_side_effect_class="READ_ONLY",
        working_directory="/tmp/repo",
        operation_id=operation_id,
        operation_parameters=parameters,
        operation_sha256=operation_sha256(operation_id, parameters),
    )


def freshness():
    return RemoteExecutionFreshness(
        nonce="typed-nonce",
        issued_at_epoch_seconds=100,
        expires_at_epoch_seconds=200,
    )


def result_data(request=None):
    if request is None:
        request = typed_request()
    return {
        "request_id": request.request_id,
        "operation_id": request.operation_id,
        "operation_parameters": dict(request.operation_parameters),
        "operation_sha256": request.operation_sha256,
        "request_envelope_sha256": "b" * 64,
        "argv": list(render_read_only_operation_argv(
            request.operation_id, request.operation_parameters
        )),
        "shell": False,
        "working_directory": request.working_directory,
        "exit_code": 0,
        "started_epoch_seconds": 100.0,
        "finished_epoch_seconds": 101.0,
        "timed_out": False,
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout": "",
        "stderr": "",
    }


def test_typed_request_binds_operation_and_parameters():
    request = typed_request("git.show.file", {"revision": "HEAD", "path": "README.md"})
    assert request.operation_id == "git.show.file"
    assert request.operation_sha256 == operation_sha256(
        "git.show.file", {"revision": "HEAD", "path": "README.md"}
    )


def test_unknown_operation_fails_closed():
    with pytest.raises(ContractValidationError, match="not an admitted"):
        typed_request("shell.exec", {})


@pytest.mark.parametrize(
    "parameters",
    [
        {"extra": "x"},
        {"revision": "HEAD"},
        {"path": "README.md"},
    ],
)
def test_operation_parameter_shape_must_match_exactly(parameters):
    with pytest.raises(ContractValidationError, match="do not match"):
        typed_request("git.show.file", parameters)


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "/etc/passwd",
        r"C:\Windows\win.ini",
        "dir/../secret.txt",
        "HEAD:README.md",
        "-n",
        "dir//file.txt",
        "dir/./file.txt",
        "line\nbreak.txt",
    ],
)
def test_git_show_path_rejects_traversal_option_and_control_forms(path):
    with pytest.raises(ContractValidationError, match="path is not admissible"):
        typed_request("git.show.file", {"revision": "HEAD", "path": path})


@pytest.mark.parametrize("revision", ["-n", "HEAD^{tree}", "", "x" * 129])
def test_git_show_revision_is_narrow(revision):
    with pytest.raises(ContractValidationError, match="revision is not admissible"):
        typed_request("git.show.file", {"revision": revision, "path": "README.md"})


def test_git_show_renders_single_non_option_object_spec():
    argv = render_read_only_operation_argv(
        "git.show.file", {"revision": "HEAD", "path": "docs/README.md"}
    )
    assert argv == GIT_READ_ONLY_PREFIX + ("show", "HEAD:docs/README.md")


def test_typed_signature_binds_parameters():
    request = typed_request("git.show.file", {"revision": "HEAD", "path": "README.md"})
    sig = sign_typed_request_hmac_sha256(request, freshness(), key=KEY)
    verify_typed_request_hmac_sha256(request, freshness(), key=KEY, signature=sig)
    changed = typed_request(
        "git.show.file", {"revision": "HEAD", "path": "pyproject.toml"}
    )
    with pytest.raises(ContractValidationError, match="signature mismatch"):
        verify_typed_request_hmac_sha256(changed, freshness(), key=KEY, signature=sig)


def test_typed_canonical_bytes_contain_no_shell_command_field():
    payload = json.loads(canonical_typed_request_bytes(typed_request(), freshness()))
    assert "command" not in payload
    assert "command_or_action" not in payload
    assert "argv" not in payload
    assert payload["operation_id"] == "git.status.short"


def test_typed_replay_guard_survives_reopen(tmp_path):
    db = tmp_path / "typed-replay.sqlite3"
    request = typed_request()
    first = DurableRemoteExecutionReplayGuard(db)
    first.consume(request, freshness(), now_epoch_seconds=150)
    second = DurableRemoteExecutionReplayGuard(db)
    with pytest.raises(ContractValidationError, match="replay detected"):
        second.consume(request, freshness(), now_epoch_seconds=151)


def test_typed_result_matches_request():
    request = typed_request()
    result = TypedRemoteExecutionResult.from_mapping(result_data(request))
    result.assert_matches(request)
    result.assert_succeeded()


def test_typed_result_rejects_argv_drift():
    data = result_data()
    data["argv"] = ["git", "status", "--short", "--untracked-files=no"]
    with pytest.raises(ContractValidationError, match="argv mismatch"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_rejects_shell_true():
    data = result_data()
    data["shell"] = True
    with pytest.raises(ContractValidationError, match="shell=false"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_rejects_request_drift():
    result = TypedRemoteExecutionResult.from_mapping(result_data())
    other = TypedRemoteExecutionRequest(
        request_id="other",
        device_id="test-device",
        expected_device_identity_fingerprint=FINGERPRINT,
        expected_device_attestation_level="SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED",
        execution_profile="READ_ONLY_DISCOVERY",
        expected_side_effect_class="READ_ONLY",
        working_directory="/tmp/repo",
        operation_id="git.status.short",
        operation_parameters={},
        operation_sha256=operation_sha256("git.status.short", {}),
    )
    with pytest.raises(ContractValidationError, match="request_id mismatch"):
        result.assert_matches(other)


def test_typed_request_parameters_are_immutable_after_validation():
    source = {"revision": "HEAD", "path": "README.md"}
    request = typed_request("git.show.file", source)
    source["path"] = "pyproject.toml"
    assert request.operation_parameters["path"] == "README.md"
    with pytest.raises(TypeError):
        request.operation_parameters["path"] = "other.txt"


def test_typed_envelope_round_trip():
    request = typed_request("git.show.file", {"revision": "HEAD", "path": "README.md"})
    fresh = freshness()
    signature = sign_typed_request_hmac_sha256(request, fresh, key=KEY)
    payload = typed_request_envelope_mapping(request, fresh, signature)
    parsed_request, parsed_freshness, parsed_signature = typed_request_envelope_from_mapping(payload)
    assert parsed_request == request
    assert parsed_freshness == fresh
    assert parsed_signature == signature


def test_typed_result_rejects_operation_digest_drift():
    data = result_data()
    data["operation_sha256"] = "0" * 64
    with pytest.raises(ContractValidationError, match="operation digest mismatch"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_requires_request_envelope_digest():
    data = result_data()
    data["request_envelope_sha256"] = "not-a-digest"
    with pytest.raises(ContractValidationError, match="request_envelope_sha256"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_working_directory_must_be_within_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    resolved = resolve_authorized_working_directory(str(allowed), [str(allowed)])
    assert resolved == allowed.resolve()
    with pytest.raises(ContractValidationError, match="outside allowed roots"):
        resolve_authorized_working_directory(str(outside), [str(allowed)])


def test_working_directory_symlink_escape_is_rejected_when_supported(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    link = allowed / "escape"
    allowed.mkdir()
    outside.mkdir()
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation unavailable")
    with pytest.raises(ContractValidationError, match="outside allowed roots"):
        resolve_authorized_working_directory(str(link), [str(allowed)])


def test_operation_registry_is_immutable():
    with pytest.raises(TypeError):
        READ_ONLY_OPERATION_SPECS["git.status.short"] = object()


def test_operation_spec_is_immutable():
    spec = READ_ONLY_OPERATION_SPECS["git.status.short"]
    with pytest.raises(FrozenInstanceError):
        spec.argv = ("git", "status")


def test_typed_result_rejects_untruncated_stdout_digest_drift():
    data = result_data()
    data["stdout"] = "changed"
    data["stdout_bytes"] = len(data["stdout"].encode("utf-8"))
    with pytest.raises(ContractValidationError, match="stdout digest mismatch"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_rejects_untruncated_stdout_byte_count_drift():
    data = result_data()
    data["stdout_bytes"] = 1
    with pytest.raises(ContractValidationError, match="stdout byte count mismatch"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_accepts_bounded_truncated_stream_metadata():
    data = result_data()
    data["stdout"] = "x" * 64
    data["stdout_bytes"] = 1000
    data["stdout_truncated"] = True
    data["stdout_sha256"] = "c" * 64
    result = TypedRemoteExecutionResult.from_mapping(data)
    assert result.stdout_truncated is True
    assert result.stdout_bytes == 1000


def test_typed_result_rejects_inconsistent_truncation_count():
    data = result_data()
    data["stdout"] = "abc"
    data["stdout_bytes"] = 3
    data["stdout_truncated"] = True
    with pytest.raises(ContractValidationError, match="truncation byte count"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_rejects_finish_before_start():
    data = result_data()
    data["started_epoch_seconds"] = 102.0
    data["finished_epoch_seconds"] = 101.0
    with pytest.raises(ContractValidationError, match="finish precedes start"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_timeout_requires_124():
    data = result_data()
    data["timed_out"] = True
    data["exit_code"] = 1
    with pytest.raises(ContractValidationError, match="exit code 124"):
        TypedRemoteExecutionResult.from_mapping(data)


def test_typed_result_assert_matches_binds_expected_envelope_digest():
    req = typed_request()
    result = TypedRemoteExecutionResult.from_mapping(result_data(req))
    result.assert_matches(req, request_envelope_sha256="b" * 64)
    with pytest.raises(ContractValidationError, match="request envelope digest mismatch"):
        result.assert_matches(req, request_envelope_sha256="c" * 64)


@pytest.mark.parametrize(
    "request_id",
    [
        "../escape",
        "..\\escape",
        "/absolute",
        r"C:\absolute",
        ".",
        "..",
        "has/slash",
        "has\\backslash",
        "has:colon",
        "has space",
        "x" * 129,
    ],
)
def test_typed_request_rejects_path_unsafe_request_id(request_id):
    with pytest.raises(ContractValidationError, match="request_id is not path-safe"):
        TypedRemoteExecutionRequest(
            request_id=request_id,
            device_id="test-device",
            expected_device_identity_fingerprint=FINGERPRINT,
            expected_device_attestation_level="SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED",
            execution_profile="READ_ONLY_DISCOVERY",
            expected_side_effect_class="READ_ONLY",
            working_directory="/tmp/repo",
            operation_id="git.status.short",
            operation_parameters={},
            operation_sha256=operation_sha256("git.status.short", {}),
        )


def test_typed_result_rejects_path_unsafe_request_id():
    data = result_data()
    data["request_id"] = "../escape"
    with pytest.raises(ContractValidationError, match="request_id is not path-safe"):
        TypedRemoteExecutionResult.from_mapping(data)
