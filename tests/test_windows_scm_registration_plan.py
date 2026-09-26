import os

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_registration import (
    WindowsScmServiceRegistrationManifest,
    WindowsScmServiceRegistrationPolicy,
    WindowsScmServiceStartType,
)
from agent_control_plane.windows_scm_registration_plan import (
    SC_MANAGER_CONNECT,
    SC_MANAGER_CREATE_SERVICE,
    SERVICE_CHANGE_CONFIG,
    SERVICE_QUERY_STATUS,
    SERVICE_START,
    SERVICE_STOP,
    WindowsScmServiceRegistrationPlanner,
    probe_windows_scm_registration_api,
)


def manifest(**overrides):
    values = dict(
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path=r"C:\Program Files\ACP\acp-supervisor.exe",
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        start_type=WindowsScmServiceStartType.DEMAND_START,
        dependencies=("Tcpip", "Dnscache"),
        credential_reference=None,
        binary_sha256="a" * 64,
    )
    values.update(overrides)
    return WindowsScmServiceRegistrationManifest(**values)


def policy_for(item, **overrides):
    values = dict(
        allowed_binary_paths=(item.binary_path,),
        allowed_accounts=(item.account_name,),
        allowed_manifest_sha256=(item.content_sha256(),),
    )
    values.update(overrides)
    return WindowsScmServiceRegistrationPolicy(**values)


def test_plan_quotes_binary_and_encodes_dependencies():
    item = manifest()
    plan = WindowsScmServiceRegistrationPlanner(
        policy=policy_for(item)
    ).compile(item)

    assert plan.binary_path_command == (
        r'"c:\program files\acp\acp-supervisor.exe"'
    )
    assert plan.dependencies_multi_sz == "Tcpip\0Dnscache\0\0"
    assert plan.requires_credential_resolution is False
    assert plan.credential_reference is None
    assert plan.desired_scm_access == (
        SC_MANAGER_CONNECT | SC_MANAGER_CREATE_SERVICE
    )
    assert plan.desired_service_access == (
        SERVICE_QUERY_STATUS
        | SERVICE_START
        | SERVICE_STOP
        | SERVICE_CHANGE_CONFIG
    )


def test_custom_account_requires_opaque_credential_reference():
    item = manifest(
        account_name=r".\acp-service-user",
        credential_reference=None,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="credential_reference required",
    ):
        WindowsScmServiceRegistrationPlanner(
            policy=policy_for(item)
        ).compile(item)


def test_custom_account_plan_never_contains_plaintext_password():
    item = manifest(
        account_name=r".\acp-service-user",
        credential_reference="windows-credential-manager:ACP-Service",
    )
    plan = WindowsScmServiceRegistrationPlanner(
        policy=policy_for(item)
    ).compile(item)

    assert plan.requires_credential_resolution is True
    assert (
        plan.credential_reference
        == "windows-credential-manager:ACP-Service"
    )
    assert not hasattr(plan, "password")


def test_virtual_service_account_requires_no_secret():
    item = manifest(
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        credential_reference=None,
    )
    plan = WindowsScmServiceRegistrationPlanner(
        policy=policy_for(item)
    ).compile(item)
    assert plan.requires_credential_resolution is False


def test_delayed_auto_start_intent_is_preserved_only_when_admitted():
    item = manifest(
        start_type=WindowsScmServiceStartType.AUTO_START,
        delayed_auto_start=True,
    )
    policy = policy_for(
        item,
        allowed_start_types=(WindowsScmServiceStartType.AUTO_START,),
        allow_delayed_auto_start=True,
    )
    plan = WindowsScmServiceRegistrationPlanner(
        policy=policy
    ).compile(item)
    assert plan.delayed_auto_start is True


@pytest.mark.skipif(os.name != "nt", reason="Windows-only SCM registration API")
def test_windows_registration_api_exports_are_present():
    probe = probe_windows_scm_registration_api()
    assert probe.available is True
    assert probe.available_exports == probe.required_exports


@pytest.mark.skipif(os.name == "nt", reason="Non-Windows probe behavior")
def test_registration_api_probe_is_explicit_off_windows():
    probe = probe_windows_scm_registration_api()
    assert probe.is_windows is False
    assert probe.available is False
