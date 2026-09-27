import pytest
from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_disposable_candidate import build_candidate,CREDENTIAL_REFERENCE

def test_candidate_is_manual_custom_account_hash_bound():
 c=build_candidate()
 assert c.plan.start_type==3
 assert c.plan.account_name.lower()==r".\acpexecutorlab"
 assert c.plan.requires_credential_resolution is True
 assert c.plan.credential_reference==CREDENTIAL_REFERENCE
 assert c.manifest.delayed_auto_start is False
 assert len(c.manifest.binary_sha256)==64
 assert "password" not in repr(c.plan).lower()

def test_policy_rejects_auto_start():
 c=build_candidate()
 from agent_control_plane.windows_scm_registration import WindowsScmServiceRegistrationManifest,WindowsScmServiceStartType
 m=WindowsScmServiceRegistrationManifest(service_name=c.manifest.service_name,display_name=c.manifest.display_name,binary_path=c.manifest.binary_path,account_name=c.manifest.account_name,start_type=WindowsScmServiceStartType.AUTO_START,credential_reference=CREDENTIAL_REFERENCE,binary_sha256=c.manifest.binary_sha256)
 with pytest.raises(AuthorityValidationError):
  c.policy.assert_admitted(m)
