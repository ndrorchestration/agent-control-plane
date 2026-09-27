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


def test_git_config_include_outside_allowed_root_is_rejected_without_consuming_replay(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    outside = tmp_path / "outside-gitconfig"
    outside.write_text(
        '[remote "origin"]\n\turl = https://example.invalid/outside-config-read\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "config", "include.path", str(outside)],
        cwd=repo,
        check=True,
    )

    request, key, identity = issue_request(
        tmp_path,
        repo,
        operation_id="git.remote.origin",
    )
    replay_db = tmp_path / "replay.sqlite3"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()

    blocked = run_verified(
        request,
        key,
        identity,
        replay_db,
        repo,
        evidence_root,
    )
    assert blocked.returncode != 0
    assert "is not admitted" in blocked.stdout
    assert not _typed_result_path(request, evidence_root).exists()

    subprocess.run(
        ["git", "config", "--unset-all", "include.path"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/in-root"],
        cwd=repo,
        check=True,
    )
    accepted = run_verified(
        request,
        key,
        identity,
        replay_db,
        repo,
        evidence_root,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    result = json.loads(
        _typed_result_path(request, evidence_root).read_text(encoding="utf-8")
    )
    assert result["stdout"].strip() == "https://example.invalid/in-root"


def test_git_includeif_is_rejected(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    config = repo / ".git" / "config"
    with config.open("a", encoding="utf-8") as handle:
        handle.write(
            '\n[includeIf "gitdir:**"]\n'
            '\tpath = ../outside-gitconfig\n'
        )
    request, key, identity = issue_request(tmp_path, repo)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    blocked = run_verified(
        request,
        key,
        identity,
        tmp_path / "replay.sqlite3",
        repo,
        evidence_root,
    )
    assert blocked.returncode != 0
    assert "is not admitted" in blocked.stdout


def test_gitdir_pointer_outside_allowed_root_is_rejected(tmp_path):
    metadata_repo = make_git_repo(tmp_path / "metadata")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(
        f"gitdir: {metadata_repo / '.git'}\n",
        encoding="utf-8",
    )
    request, key, identity = issue_request(tmp_path, worktree)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    blocked = run_verified(
        request,
        key,
        identity,
        tmp_path / "replay.sqlite3",
        worktree,
        evidence_root,
    )
    assert blocked.returncode != 0
    assert "git directory is outside allowed roots" in blocked.stdout


@pytest.mark.parametrize(
    "section_text",
    [
        '[filter "evil"]\n\tclean = python evil.py\n',
        '[diff "evil"]\n\ttextconv = python evil.py\n',
        '[include] # trailing comment\n\tpath = ../outside\n',
    ],
)
def test_git_config_helper_sections_are_rejected(tmp_path, section_text):
    repo = make_git_repo(tmp_path / "repo")
    config = repo / ".git" / "config"
    with config.open("a", encoding="utf-8") as handle:
        handle.write("\n" + section_text)
    request, key, identity = issue_request(tmp_path, repo)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    blocked = run_verified(
        request,
        key,
        identity,
        tmp_path / "replay.sqlite3",
        repo,
        evidence_root,
    )
    assert blocked.returncode != 0
    assert "is not admitted" in blocked.stdout


def test_git_core_worktree_is_rejected(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    subprocess.run(
        ["git", "config", "core.worktree", str(outside)],
        cwd=repo,
        check=True,
    )
    request, key, identity = issue_request(tmp_path, repo)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    blocked = run_verified(
        request,
        key,
        identity,
        tmp_path / "replay.sqlite3",
        repo,
        evidence_root,
    )
    assert blocked.returncode != 0
    assert "git core.worktree is not admitted" in blocked.stdout


def test_git_object_alternates_are_rejected(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(
        str(tmp_path / "outside-objects") + "\n",
        encoding="utf-8",
    )
    request, key, identity = issue_request(tmp_path, repo)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    blocked = run_verified(
        request,
        key,
        identity,
        tmp_path / "replay.sqlite3",
        repo,
        evidence_root,
    )
    assert blocked.returncode != 0
    assert "git object alternates are not admitted" in blocked.stdout


def test_executor_scrubs_inherited_git_environment(tmp_path, monkeypatch):
    repo = make_git_repo(tmp_path / "repo")
    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    foreign = make_git_repo(tmp_path / "foreign")
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(foreign))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "attacker.cfg"))

    argv = READ_ONLY_OPERATION_SPECS["git.status.short"].argv
    result = execute_read_only_argv_bounded(argv, cwd=repo)

    assert result["exit_code"] == 0
    assert "local.txt" in result["stdout"]


def test_existing_result_path_blocks_without_overwrite_or_replay_consumption(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    request, key, identity = issue_request(tmp_path, repo)
    replay_db = tmp_path / "replay.sqlite3"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    output = _typed_result_path(request, evidence_root)
    output.write_text("sentinel\n", encoding="utf-8")

    blocked = run_verified(
        request,
        key,
        identity,
        replay_db,
        repo,
        evidence_root,
    )
    assert blocked.returncode != 0
    assert "typed result path already exists" in blocked.stdout
    assert output.read_text(encoding="utf-8") == "sentinel\n"

    output.unlink()
    accepted = run_verified(
        request,
        key,
        identity,
        replay_db,
        repo,
        evidence_root,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert output.exists()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["request_id"] == json.loads(
        request.read_text(encoding="utf-8")
    )["request"]["request_id"]
