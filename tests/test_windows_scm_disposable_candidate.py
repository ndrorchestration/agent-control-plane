from pathlib import Path
import pytest
from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_disposable_candidate import build_candidate,CREDENTIAL_REFERENCE

def make_probe(tmp_path):
 p=tmp_path/"staging"/"ACP-Executor-Isolation-Lab"/"probe.exe";p.parent.mkdir(parents=True);p.write_bytes(b"MZ disposable fixture");return p

def test_candidate_is_manual_custom_account_hash_bound(tmp_path):
 c=build_candidate(probe_executable=str(make_probe(tmp_path)))
 assert c.plan.start_type==3
 assert c.plan.account_name.lower()==r".\acpexecutorlab"
 assert c.plan.requires_credential_resolution is True
 assert c.plan.credential_reference==CREDENTIAL_REFERENCE
 assert c.manifest.delayed_auto_start is False
 assert len(c.manifest.binary_sha256)==64
 assert "password" not in repr(c.plan).lower()

def test_candidate_rejects_executable_outside_lab(tmp_path):
 p=tmp_path/"probe.exe";p.write_bytes(b"MZ")
 with pytest.raises(ValueError,match="disposable"):
  build_candidate(probe_executable=str(p))
