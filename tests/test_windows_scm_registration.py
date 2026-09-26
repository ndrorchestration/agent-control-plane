import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_registration import (
    WindowsScmServiceRegistrationManifest,
    WindowsScmServiceRegistrationPolicy,
    WindowsScmServiceStartType,
)


def manifest(**overrides):
    values = dict(
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path=r"C:\ACP\acp-supervisor.exe",
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        start_type=WindowsScmServiceStartType.DEMAND_START,
        description="ACP experimental Windows supervisor service",
        dependencies=("Tcpip",),
        delayed_auto_start=False,
        credential_reference="windows-credential-manager:ACPAgentControlPlane",
        binary_sha256="a" * 64,
    )
    values.update(overrides)
    return WindowsScmServiceRegistrationManifest(**values)


def policy(**overrides):
    values = dict(
        allowed_binary_paths=(r"C:\ACP\acp-supervisor.exe",),
        allowed_accounts=(r"NT SERVICE\ACPAgentControlPlane",),
    )
    values.update(overrides)
    return WindowsScmServiceRegistrationPolicy(**values)


def test_manifest_canonical_identity_is_stable():
    first = manifest()
    second = manifest()
    assert first.canonical_payload() == second.canonical_payload()
    assert first.content_sha256() == second.content_sha256()
    assert len(first.content_sha256()) == 64


def test_argument_change_changes_manifest_identity():
    first = manifest()
    second = manifest(description="changed")
    assert first.content_sha256() != second.content_sha256()


def test_registration_policy_admits_exact_demand_start_manifest():
    item = manifest()
    digest = policy().assert_admitted(item)
    assert digest == item.content_sha256()


def test_relative_binary_path_fails_closed():
    with pytest.raises(
        AuthorityValidationError,
        match="absolute Windows path",
    ):
        manifest(binary_path="acp-supervisor.exe")


def test_local_system_fails_closed_by_default():
    item = manifest(account_name="LocalSystem")
    p = WindowsScmServiceRegistrationPolicy(
        allowed_binary_paths=(r"C:\ACP\acp-supervisor.exe",),
        allowed_accounts=("LocalSystem",),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="LocalSystem service account not admitted",
    ):
        p.assert_admitted(item)


def test_local_system_requires_explicit_policy_override():
    item = manifest(account_name="LocalSystem")
    p = WindowsScmServiceRegistrationPolicy(
        allowed_binary_paths=(r"C:\ACP\acp-supervisor.exe",),
        allowed_accounts=("LocalSystem",),
        allow_local_system=True,
    )
    assert p.assert_admitted(item) == item.content_sha256()


def test_auto_start_is_rejected_by_default():
    item = manifest(
        start_type=WindowsScmServiceStartType.AUTO_START,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="start type not admitted",
    ):
        policy().assert_admitted(item)


def test_delayed_auto_start_requires_explicit_admission():
    item = manifest(
        start_type=WindowsScmServiceStartType.AUTO_START,
        delayed_auto_start=True,
    )
    p = policy(
        allowed_start_types=(
            WindowsScmServiceStartType.AUTO_START,
        ),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="delayed auto-start not admitted",
    ):
        p.assert_admitted(item)

    admitted = policy(
        allowed_start_types=(
            WindowsScmServiceStartType.AUTO_START,
        ),
        allow_delayed_auto_start=True,
    )
    assert admitted.assert_admitted(item) == item.content_sha256()


def test_binary_digest_required_by_default():
    item = manifest(binary_sha256=None)
    with pytest.raises(
        AuthorityValidationError,
        match="binary_sha256 is required",
    ):
        policy().assert_admitted(item)


def test_wrong_binary_path_fails_closed():
    item = manifest(binary_path=r"C:\Other\acp-supervisor.exe")
    with pytest.raises(
        AuthorityValidationError,
        match="binary path not admitted",
    ):
        policy().assert_admitted(item)


def test_wrong_account_fails_closed():
    item = manifest(account_name=r".\SomeUser")
    with pytest.raises(
        AuthorityValidationError,
        match="account not admitted",
    ):
        policy().assert_admitted(item)


def test_manifest_hash_allowlist_binds_exact_install_intent():
    item = manifest()
    wrong = manifest(display_name="Different")
    p = policy(
        allowed_manifest_sha256=(item.content_sha256(),),
    )
    assert p.assert_admitted(item) == item.content_sha256()
    with pytest.raises(
        AuthorityValidationError,
        match="manifest not admitted",
    ):
        p.assert_admitted(wrong)


def test_dependencies_cannot_duplicate_or_self_reference():
    with pytest.raises(
        AuthorityValidationError,
        match="duplicates",
    ):
        manifest(dependencies=("Tcpip", "tcpip"))
    with pytest.raises(
        AuthorityValidationError,
        match="depend on itself",
    ):
        manifest(dependencies=("ACPAgentControlPlane",))


def test_delayed_auto_start_requires_auto_start_manifest():
    with pytest.raises(
        AuthorityValidationError,
        match="requires AUTO_START",
    ):
        manifest(delayed_auto_start=True)
