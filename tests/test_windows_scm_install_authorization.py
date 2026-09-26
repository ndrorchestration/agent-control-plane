import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_binary_verification import (
    WindowsScmBinaryVerification,
    WindowsScmRegistrationAdmissionResult,
)
from agent_control_plane.windows_scm_install_authorization import (
    WindowsScmInstallationAuthorizationStore,
    WindowsScmInstallationTarget,
    build_windows_scm_installation_target,
    windows_scm_registration_plan_sha256,
)
from agent_control_plane.windows_scm_registration import (
    WindowsScmServiceRegistrationManifest,
    WindowsScmServiceRegistrationPolicy,
)
from agent_control_plane.windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlanner,
)


def manifest():
    return WindowsScmServiceRegistrationManifest(
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path=r"C:\ACP\acp-supervisor.exe",
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        binary_sha256="a" * 64,
    )


def plan_for(item):
    policy = WindowsScmServiceRegistrationPolicy(
        allowed_binary_paths=(item.binary_path,),
        allowed_accounts=(item.account_name,),
        allowed_manifest_sha256=(item.content_sha256(),),
    )
    return WindowsScmServiceRegistrationPlanner(
        policy=policy
    ).compile(item)


def admission_for(item):
    return WindowsScmRegistrationAdmissionResult(
        manifest_sha256=item.content_sha256(),
        binary=WindowsScmBinaryVerification(
            binary_path=item.binary_path,
            expected_sha256=item.binary_sha256,
            actual_sha256=item.binary_sha256,
            size_bytes=123,
            modified_time_ns=456,
        ),
    )


def target():
    item = manifest()
    return build_windows_scm_installation_target(
        manifest=item,
        admission=admission_for(item),
        plan=plan_for(item),
    )


def test_registration_plan_identity_is_stable():
    item = manifest()
    first = plan_for(item)
    second = plan_for(item)
    assert windows_scm_registration_plan_sha256(first) == (
        windows_scm_registration_plan_sha256(second)
    )


def test_build_target_binds_manifest_binary_and_plan():
    item = manifest()
    result = build_windows_scm_installation_target(
        manifest=item,
        admission=admission_for(item),
        plan=plan_for(item),
    )
    assert result.service_name == item.service_name
    assert result.manifest_sha256 == item.content_sha256()
    assert result.binary_sha256 == item.binary_sha256
    assert len(result.registration_plan_sha256) == 64


def test_build_target_rejects_admission_manifest_drift():
    item = manifest()
    admission = WindowsScmRegistrationAdmissionResult(
        manifest_sha256="b" * 64,
        binary=admission_for(item).binary,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="admission manifest identity mismatch",
    ):
        build_windows_scm_installation_target(
            manifest=item,
            admission=admission,
            plan=plan_for(item),
        )


def test_build_target_rejects_binary_drift():
    item = manifest()
    admission = WindowsScmRegistrationAdmissionResult(
        manifest_sha256=item.content_sha256(),
        binary=WindowsScmBinaryVerification(
            binary_path=item.binary_path,
            expected_sha256=item.binary_sha256,
            actual_sha256="b" * 64,
            size_bytes=123,
            modified_time_ns=456,
        ),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="actual binary identity",
    ):
        build_windows_scm_installation_target(
            manifest=item,
            admission=admission,
            plan=plan_for(item),
        )


def test_issue_and_consume_exact_target(tmp_path):
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install-auth.sqlite3"
    )
    expected = target()
    issued = store.issue(
        authorization_id="install-1",
        target=expected,
        authorized_by="operator-a",
        issued_at="2026-09-26T09:00:00Z",
        expires_at="2026-09-26T10:00:00Z",
    )
    assert issued.consumed_at is None

    consumed = store.consume(
        "install-1",
        target=expected,
        now="2026-09-26T09:05:00Z",
    )
    assert consumed.consumed_at == "2026-09-26T09:05:00Z"


def test_consumption_is_single_use(tmp_path):
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install-auth.sqlite3"
    )
    expected = target()
    store.issue(
        authorization_id="install-1",
        target=expected,
        authorized_by="operator-a",
        issued_at="2026-09-26T09:00:00Z",
        expires_at="2026-09-26T10:00:00Z",
    )
    store.consume(
        "install-1",
        target=expected,
        now="2026-09-26T09:05:00Z",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="already consumed",
    ):
        store.consume(
            "install-1",
            target=expected,
            now="2026-09-26T09:06:00Z",
        )


def test_expired_authorization_fails_closed(tmp_path):
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install-auth.sqlite3"
    )
    expected = target()
    store.issue(
        authorization_id="install-1",
        target=expected,
        authorized_by="operator-a",
        issued_at="2026-09-26T09:00:00Z",
        expires_at="2026-09-26T09:10:00Z",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="expired",
    ):
        store.consume(
            "install-1",
            target=expected,
            now="2026-09-26T09:10:00Z",
        )


def test_wrong_target_fails_closed(tmp_path):
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install-auth.sqlite3"
    )
    expected = target()
    store.issue(
        authorization_id="install-1",
        target=expected,
        authorized_by="operator-a",
        issued_at="2026-09-26T09:00:00Z",
        expires_at="2026-09-26T10:00:00Z",
    )
    changed = WindowsScmInstallationTarget(
        service_name=expected.service_name,
        manifest_sha256=expected.manifest_sha256,
        binary_sha256=expected.binary_sha256,
        registration_plan_sha256="b" * 64,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="does not match target",
    ):
        store.consume(
            "install-1",
            target=changed,
            now="2026-09-26T09:05:00Z",
        )


def test_authorization_id_conflict_fails_closed(tmp_path):
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install-auth.sqlite3"
    )
    expected = target()
    store.issue(
        authorization_id="install-1",
        target=expected,
        authorized_by="operator-a",
        issued_at="2026-09-26T09:00:00Z",
        expires_at="2026-09-26T10:00:00Z",
    )
    changed = WindowsScmInstallationTarget(
        service_name="OtherService",
        manifest_sha256=expected.manifest_sha256,
        binary_sha256=expected.binary_sha256,
        registration_plan_sha256=expected.registration_plan_sha256,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="authorization_id conflict",
    ):
        store.issue(
            authorization_id="install-1",
            target=changed,
            authorized_by="operator-a",
            issued_at="2026-09-26T09:00:00Z",
            expires_at="2026-09-26T10:00:00Z",
        )
