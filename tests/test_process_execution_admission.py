import os
import sys
from pathlib import Path

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.process_execution_admission import (
    AdmittedManagedProcessController,
    ProcessExecutionAdmissionPolicy,
    managed_process_spec_sha256,
)
from agent_control_plane.process_runtime import ManagedProcessSpec


def canonical(path):
    return str(Path(path).resolve())


def admitted_policy(tmp_path, spec, **overrides):
    values = dict(
        allowed_executables=(sys.executable,),
        allowed_cwd_roots=(str(tmp_path),),
        allowed_environment_keys=("ACP_TEST",),
        forbidden_environment_keys=("SECRET", "TOKEN"),
        allowed_spec_sha256=(managed_process_spec_sha256(spec),),
        allow_inherited_environment=False,
        allow_inherited_cwd=False,
    )
    values.update(overrides)
    return ProcessExecutionAdmissionPolicy(**values)


def test_admitted_spec_starts_real_child(tmp_path):
    spec = ManagedProcessSpec(
        process_id="allowed",
        argv=(sys.executable, "-c", "print('ok')"),
        cwd=str(tmp_path),
        env={"ACP_TEST": "1"},
    )
    controller = AdmittedManagedProcessController(
        spec,
        admission_policy=admitted_policy(tmp_path, spec),
    )
    started = controller.start()
    assert started.pid is not None
    controller._process.wait(timeout=5)
    assert controller.observe().returncode == 0


def test_unlisted_executable_fails_before_spawn(tmp_path):
    spec = ManagedProcessSpec(
        process_id="bad-exe",
        argv=("/definitely/not/admitted",),
        cwd=str(tmp_path),
        env={"ACP_TEST": "1"},
    )
    policy = ProcessExecutionAdmissionPolicy(
        allowed_executables=(sys.executable,),
        allowed_cwd_roots=(str(tmp_path),),
        allowed_environment_keys=("ACP_TEST",),
    )
    controller = AdmittedManagedProcessController(
        spec,
        admission_policy=policy,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="executable not admitted",
    ):
        controller.start()
    assert controller.observe().pid is None


def test_inherited_environment_is_fail_closed_by_default(tmp_path):
    spec = ManagedProcessSpec(
        process_id="inherit-env",
        argv=(sys.executable, "-c", "print('x')"),
        cwd=str(tmp_path),
        env=None,
    )
    policy = ProcessExecutionAdmissionPolicy(
        allowed_executables=(sys.executable,),
        allowed_cwd_roots=(str(tmp_path),),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="inherited environment not admitted",
    ):
        policy.assert_admitted(spec)


def test_unexpected_or_forbidden_environment_key_fails(tmp_path):
    unexpected = ManagedProcessSpec(
        process_id="unexpected-env",
        argv=(sys.executable, "-c", "print('x')"),
        cwd=str(tmp_path),
        env={"OTHER": "1"},
    )
    policy = ProcessExecutionAdmissionPolicy(
        allowed_executables=(sys.executable,),
        allowed_cwd_roots=(str(tmp_path),),
        allowed_environment_keys=("ACP_TEST",),
        forbidden_environment_keys=("SECRET",),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="environment key not admitted",
    ):
        policy.assert_admitted(unexpected)

    forbidden = ManagedProcessSpec(
        process_id="forbidden-env",
        argv=(sys.executable, "-c", "print('x')"),
        cwd=str(tmp_path),
        env={"SECRET": "value"},
    )
    with pytest.raises(
        AuthorityValidationError,
        match="forbidden key",
    ):
        policy.assert_admitted(forbidden)


def test_cwd_outside_allowed_root_fails(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    spec = ManagedProcessSpec(
        process_id="bad-cwd",
        argv=(sys.executable, "-c", "print('x')"),
        cwd=str(outside),
        env={"ACP_TEST": "1"},
    )
    policy = ProcessExecutionAdmissionPolicy(
        allowed_executables=(sys.executable,),
        allowed_cwd_roots=(str(tmp_path),),
        allowed_environment_keys=("ACP_TEST",),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="cwd not admitted",
    ):
        policy.assert_admitted(spec)


def test_spec_fingerprint_detects_argument_change(tmp_path):
    admitted = ManagedProcessSpec(
        process_id="fingerprinted",
        argv=(sys.executable, "-c", "print('one')"),
        cwd=str(tmp_path),
        env={"ACP_TEST": "1"},
    )
    changed = ManagedProcessSpec(
        process_id="fingerprinted",
        argv=(sys.executable, "-c", "print('two')"),
        cwd=str(tmp_path),
        env={"ACP_TEST": "1"},
    )
    policy = admitted_policy(tmp_path, admitted)
    assert policy.assert_admitted(admitted) == managed_process_spec_sha256(
        admitted
    )
    with pytest.raises(
        AuthorityValidationError,
        match="fingerprint not admitted",
    ):
        policy.assert_admitted(changed)


def test_required_uid_binding_fails_closed_on_mismatch(tmp_path):
    spec = ManagedProcessSpec(
        process_id="uid-bound",
        argv=(sys.executable, "-c", "print('x')"),
        cwd=str(tmp_path),
        env={"ACP_TEST": "1"},
    )
    current_uid = getattr(os, "geteuid", lambda: 0)()
    policy = admitted_policy(
        tmp_path,
        spec,
        required_effective_uid=current_uid + 1,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="effective uid not admitted",
    ):
        policy.assert_admitted(
            spec,
            effective_uid=current_uid,
        )


def test_inherited_cwd_requires_explicit_opt_in(tmp_path):
    spec = ManagedProcessSpec(
        process_id="inherit-cwd",
        argv=(sys.executable, "-c", "print('x')"),
        cwd=None,
        env={"ACP_TEST": "1"},
    )
    policy = ProcessExecutionAdmissionPolicy(
        allowed_executables=(sys.executable,),
        allowed_environment_keys=("ACP_TEST",),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="inherited cwd not admitted",
    ):
        policy.assert_admitted(spec)
