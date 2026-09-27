from pathlib import Path

import pytest

from agent_control_plane.executor_process_boundary import (
    ExecutorAssuranceTarget,
    ExecutorProcessBoundaryError,
    ExecutorProcessBoundaryEvidence,
    assess_executor_process_boundary,
    sha256_file,
)


def evidence(tmp_path: Path, **overrides):
    exe = tmp_path / "executor.exe"
    exe.write_bytes(b"executor-binary")
    repo = tmp_path / "repo"
    repo.mkdir()
    auth = tmp_path / "stores" / "authorization.sqlite3"
    journal = tmp_path / "stores" / "journal.sqlite3"
    custody = tmp_path / "custody" / "rollback.bin"
    values = {
        "executable_path": str(exe.resolve()),
        "executable_sha256": sha256_file(exe),
        "os_user": "acp-test-user",
        "repository_roots": (str(repo.resolve()),),
        "authorization_store_path": str(auth.resolve()),
        "journal_store_path": str(journal.resolve()),
        "rollback_custody_path": str(custody.resolve()),
    }
    values.update(overrides)
    return ExecutorProcessBoundaryEvidence(**values)


def test_local_test_boundary_accepts_recorded_identity_and_separated_paths(tmp_path):
    result = assess_executor_process_boundary(
        evidence(tmp_path),
        target=ExecutorAssuranceTarget.LOCAL_TEST,
    )
    assert result.admitted is True
    assert result.executable_identity_recorded is True
    assert result.store_paths_separated is True
    assert result.service_identity_verified is False


def test_high_assurance_fails_closed_without_os_controls(tmp_path):
    result = assess_executor_process_boundary(
        evidence(tmp_path),
        target=ExecutorAssuranceTarget.HIGH_ASSURANCE,
    )
    assert result.admitted is False
    assert "dedicated service identity not established" in result.reasons
    assert "trusted launcher identity not established" in result.reasons
    assert "ACL separation not established" in result.reasons
    assert "OS isolation not established" in result.reasons
    assert "peer-process tamper resistance not established" in result.reasons


def test_high_assurance_requires_all_declared_controls(tmp_path):
    result = assess_executor_process_boundary(
        evidence(
            tmp_path,
            dedicated_service_identity=True,
            trusted_launcher_identity=True,
            acl_separation_verified=True,
            os_isolation_verified=True,
            peer_process_tamper_resistance_verified=True,
        ),
        target=ExecutorAssuranceTarget.HIGH_ASSURANCE,
    )
    assert result.admitted is True


def test_store_path_alias_to_repository_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    exe = tmp_path / "executor.exe"
    exe.write_bytes(b"executor-binary")
    root = str(repo.resolve())
    record = ExecutorProcessBoundaryEvidence(
        executable_path=str(exe.resolve()),
        executable_sha256=sha256_file(exe),
        os_user="acp-test-user",
        repository_roots=(root,),
        authorization_store_path=root,
        journal_store_path=str((tmp_path / "journal.sqlite3").resolve()),
        rollback_custody_path=str((tmp_path / "rollback.bin").resolve()),
    )

    result = assess_executor_process_boundary(
        record,
        target=ExecutorAssuranceTarget.LOCAL_TEST,
    )

    assert result.admitted is False
    assert "store/repository path separation not established" in result.reasons


def test_duplicate_store_paths_are_rejected(tmp_path):
    shared = str((tmp_path / "shared.sqlite3").resolve())
    result = assess_executor_process_boundary(
        evidence(
            tmp_path,
            authorization_store_path=shared,
            journal_store_path=shared,
        ),
        target=ExecutorAssuranceTarget.LOCAL_TEST,
    )
    assert result.admitted is False


def test_invalid_executable_hash_is_rejected(tmp_path):
    with pytest.raises(ExecutorProcessBoundaryError, match="lowercase sha256"):
        evidence(tmp_path, executable_sha256="not-a-hash")
