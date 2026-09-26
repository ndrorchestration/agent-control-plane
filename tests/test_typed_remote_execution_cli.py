import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_control_plane.contract.model import ContractValidationError
from agent_control_plane.typed_remote_execution import (
    READ_ONLY_OPERATION_SPECS,
    _execute_argv_bounded as execute_read_only_argv_bounded,
    render_read_only_operation_argv,
)


ROOT = Path(__file__).resolve().parents[1]
ISSUER = ROOT / "scripts" / "issue_remote_execution_request.py"
VERIFIER = ROOT / "scripts" / "verify_remote_execution_request.py"
EXECUTOR = ROOT / "scripts" / "execute_verified_typed_request.py"


def make_git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    return path


def write_identity(path: Path) -> Path:
    payload = {
        "device_name": "test-device",
        "fingerprint_sha256": "a" * 64,
        "attestation_level": "SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def issue_request(
    tmp_path: Path,
    repo: Path,
    *,
    operation_id: str = "git.status.short",
    parameters_file: Path | None = None,
    name: str = "request.json",
) -> tuple[Path, Path, Path]:
    key = tmp_path / "key.bin"
    key.write_bytes(b"k" * 32)
    identity = write_identity(tmp_path / "identity.json")
    request = tmp_path / name
    command = [
        sys.executable,
        str(ISSUER),
        "--device",
        "test-device",
        "--device-fingerprint",
        "a" * 64,
        "--device-attestation-level",
        "SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED",
        "--cwd",
        str(repo),
        "--operation-id",
        operation_id,
        "--ttl",
        "120",
        "--key",
        str(key),
        "--output",
        str(request),
    ]
    if parameters_file is not None:
        command.extend(["--parameters-file", str(parameters_file)])
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return request, key, identity


def run_verified(
    request: Path,
    key: Path,
    identity: Path,
    replay_db: Path,
    allowed_root: Path,
    evidence_root: Path,
):
    return subprocess.run(
        [
            sys.executable,
            str(EXECUTOR),
            str(request),
            "--key",
            str(key),
            "--device-identity",
            str(identity),
            "--replay-db",
            str(replay_db),
            "--allowed-root",
            str(allowed_root),
            "--evidence-root",
            str(evidence_root),
        ],
        capture_output=True,
        text=True,
    )


def test_issuer_v2_envelope_contains_no_shell_text(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    request, _, _ = issue_request(tmp_path, repo)
    payload = json.loads(request.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "ndr.remote-execution-request.v2"
    request_payload = payload["request"]
    assert request_payload["operation_id"] == "git.status.short"
    assert request_payload["operation_parameters"] == {}
    assert "command" not in request_payload
    assert "command_or_action" not in request_payload
    assert "argv" not in request_payload


def _typed_result_path(request: Path, evidence_root: Path) -> Path:
    payload = json.loads(request.read_text(encoding="utf-8"))
    request_id = payload["request"]["request_id"]
    return evidence_root / f"{request_id}.typed-result.json"


def test_verified_executor_passes_then_replay_fails(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    request, key, identity = issue_request(tmp_path, repo)
    replay_db = tmp_path / "replay.sqlite3"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    first = run_verified(
        request, key, identity, replay_db, repo, evidence_root
    )
    assert first.returncode == 0, first.stdout + first.stderr
    output = _typed_result_path(request, evidence_root)
    assert output.exists()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["shell"] is False
    assert result["argv"] == list(
        READ_ONLY_OPERATION_SPECS["git.status.short"].argv
    )
    assert result["request_envelope_sha256"] == hashlib.sha256(
        request.read_bytes()
    ).hexdigest()

    second = run_verified(
        request, key, identity, replay_db, repo, evidence_root
    )
    assert second.returncode != 0
    assert "replay detected" in second.stdout


def test_scope_failure_does_not_consume_replay(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    other = tmp_path / "other"
    other.mkdir()
    request, key, identity = issue_request(tmp_path, repo)
    replay_db = tmp_path / "replay.sqlite3"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()

    blocked = run_verified(
        request, key, identity, replay_db, other, evidence_root
    )
    assert blocked.returncode != 0
    assert "outside allowed roots" in blocked.stdout
    assert not _typed_result_path(request, evidence_root).exists()

    accepted = run_verified(
        request, key, identity, replay_db, repo, evidence_root
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert _typed_result_path(request, evidence_root).exists()


def test_parameter_file_git_show_round_trip(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    (repo / "sample.txt").write_text(
        "typed-operation-content\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "sample.txt"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    params = tmp_path / "params.json"
    params.write_text(
        json.dumps({"revision": "HEAD", "path": "sample.txt"}),
        encoding="utf-8",
    )
    request, key, identity = issue_request(
        tmp_path,
        repo,
        operation_id="git.show.file",
        parameters_file=params,
        name="show-request.json",
    )
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    completed = run_verified(
        request,
        key,
        identity,
        tmp_path / "replay.sqlite3",
        repo,
        evidence_root,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = _typed_result_path(request, evidence_root)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["stdout"] == "typed-operation-content\n"
    assert result["argv"] == list(
        render_read_only_operation_argv(
            "git.show.file", {"revision": "HEAD", "path": "sample.txt"}
        )
    )


def test_verified_executor_requires_existing_evidence_root(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    request, key, identity = issue_request(tmp_path, repo)
    missing = tmp_path / "missing-evidence"
    completed = run_verified(
        request,
        key,
        identity,
        tmp_path / "replay.sqlite3",
        repo,
        missing,
    )
    assert completed.returncode != 0
    assert "evidence root" in completed.stdout
    assert not missing.exists()


def test_bounded_executor_truncates_stored_output_but_hashes_full_stream(tmp_path):
    argv = (
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('x' * 1000)",
    )
    result = execute_read_only_argv_bounded(
        argv,
        cwd=tmp_path,
        timeout_seconds=5,
        max_output_bytes=64,
    )
    assert result["exit_code"] == 0
    assert result["stdout_bytes"] == 1000
    assert result["stdout_truncated"] is True
    assert len(result["stdout"].encode("utf-8")) == 64
    assert result["stdout_sha256"] == hashlib.sha256(b"x" * 1000).hexdigest()


def test_bounded_executor_times_out(tmp_path):
    argv = (
        sys.executable,
        "-c",
        "import time; time.sleep(2)",
    )
    result = execute_read_only_argv_bounded(
        argv,
        cwd=tmp_path,
        timeout_seconds=1,
        max_output_bytes=64,
    )
    assert result["exit_code"] == 124
    assert result["timed_out"] is True


def test_bounded_executor_rejects_bounds_above_contract(tmp_path):
    with pytest.raises(ContractValidationError, match="timeout_seconds"):
        execute_read_only_argv_bounded(
            (sys.executable, "-c", "print('ok')"),
            cwd=tmp_path,
            timeout_seconds=31,
        )
    with pytest.raises(ContractValidationError, match="max_output_bytes"):
        execute_read_only_argv_bounded(
            (sys.executable, "-c", "print('ok')"),
            cwd=tmp_path,
            max_output_bytes=(1024 * 1024) + 1,
        )


def test_standalone_verifier_scope_failure_does_not_consume_replay(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    other = tmp_path / "other"
    other.mkdir()
    request, key, identity = issue_request(tmp_path, repo)
    replay_db = tmp_path / "verify-replay.sqlite3"

    def verify(root):
        return subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(request),
                "--key",
                str(key),
                "--device-identity",
                str(identity),
                "--replay-db",
                str(replay_db),
                "--allowed-root",
                str(root),
            ],
            capture_output=True,
            text=True,
        )

    blocked = verify(other)
    assert blocked.returncode != 0
    assert "outside allowed roots" in blocked.stdout

    accepted = verify(repo)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "REMOTE_REQUEST=PASS" in accepted.stdout


def test_git_status_readonly_policy_leaves_index_bytes_unchanged(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    tracked = repo / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    tracked.write_text("after\n", encoding="utf-8")

    index_path = repo / ".git" / "index"
    before = index_path.read_bytes()
    argv = READ_ONLY_OPERATION_SPECS["git.status.short"].argv
    result = execute_read_only_argv_bounded(argv, cwd=repo)
    after = index_path.read_bytes()

    assert result["exit_code"] == 0
    assert before == after
    assert "tracked.txt" in result["stdout"]
