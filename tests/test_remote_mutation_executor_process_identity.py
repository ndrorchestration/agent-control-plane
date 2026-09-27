from __future__ import annotations

import getpass
import hashlib
from pathlib import Path
import sys

import pytest

from agent_control_plane.remote_mutation_executor_process_identity import (
    EXECUTOR_PROCESS_EVIDENCE_LEVEL,
    EXECUTOR_PROCESS_IDENTITY_SCHEMA_VERSION,
    ExecutorProcessIdentityError,
    ExecutorProcessIdentityRecord,
    build_executor_process_policy,
    inspect_executor_process_identity,
)

EXECUTOR_ID = "acp.repository-mutation-executor.v0-candidate"


def current_executable():
    path = Path(sys.executable).resolve(strict=True)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def policy(*, path=None, sha=None, username=None, executor_id=EXECUTOR_ID):
    current_path, current_sha = current_executable()
    return build_executor_process_policy(
        policy_id="policy:test",
        executor_id=executor_id,
        executable_paths=[path or current_path],
        executable_sha256=[sha or current_sha],
        usernames=[username or getpass.getuser()],
    )


def test_exact_current_process_identity_satisfies_policy_without_authorizing():
    current_path, current_sha = current_executable()
    record = inspect_executor_process_identity(
        policy(),
        executor_id=EXECUTOR_ID,
    )

    assert record.schema_version == EXECUTOR_PROCESS_IDENTITY_SCHEMA_VERSION
    assert record.evidence_level == EXECUTOR_PROCESS_EVIDENCE_LEVEL
    assert record.executable_path == str(current_path).lower() if sys.platform == "win32" else str(current_path)
    assert record.executable_sha256 == current_sha
    assert record.policy_satisfied is True
    assert record.execution_authorized is False
    assert record.mutation_executed is False
    assert len(record.evidence_sha256) == 64


def test_wrong_hash_fails_policy():
    record = inspect_executor_process_identity(
        policy(sha="0" * 64),
        executor_id=EXECUTOR_ID,
    )
    assert record.executable_hash_allowed is False
    assert record.policy_satisfied is False


def test_wrong_username_fails_policy():
    record = inspect_executor_process_identity(
        policy(username="definitely-not-current-user"),
        executor_id=EXECUTOR_ID,
    )
    assert record.username_allowed is False
    assert record.policy_satisfied is False


def test_wrong_executor_id_fails_all_policy_checks():
    record = inspect_executor_process_identity(
        policy(),
        executor_id="other-executor",
    )
    assert record.policy_satisfied is False
    assert record.executable_path_allowed is False
    assert record.executable_hash_allowed is False
    assert record.username_allowed is False


def test_relative_executable_path_is_rejected():
    current_path, current_sha = current_executable()
    with pytest.raises(ExecutorProcessIdentityError, match="absolute"):
        build_executor_process_policy(
            policy_id="policy:test",
            executor_id=EXECUTOR_ID,
            executable_paths=["python.exe"],
            executable_sha256=[current_sha],
            usernames=[getpass.getuser()],
        )


def test_record_cannot_authorize_execution():
    current_path, current_sha = current_executable()
    with pytest.raises(ExecutorProcessIdentityError, match="cannot authorize"):
        ExecutorProcessIdentityRecord(
            policy_id="policy:test",
            executor_id=EXECUTOR_ID,
            executable_path=str(current_path),
            executable_sha256=current_sha,
            username=getpass.getuser(),
            pid=1,
            platform_system="test",
            executable_path_allowed=True,
            executable_hash_allowed=True,
            username_allowed=True,
            policy_satisfied=True,
            execution_authorized=True,
        )


def test_policy_satisfied_cannot_disagree_with_checks():
    current_path, current_sha = current_executable()
    with pytest.raises(ExecutorProcessIdentityError, match="conjunction"):
        ExecutorProcessIdentityRecord(
            policy_id="policy:test",
            executor_id=EXECUTOR_ID,
            executable_path=str(current_path),
            executable_sha256=current_sha,
            username=getpass.getuser(),
            pid=1,
            platform_system="test",
            executable_path_allowed=True,
            executable_hash_allowed=False,
            username_allowed=True,
            policy_satisfied=True,
        )
