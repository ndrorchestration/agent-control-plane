from pathlib import Path
import pytest
from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_identity_probe import PROBE_ID, run_probe, validate_probe_root

def test_probe_accepts_only_disposable_lab(tmp_path):
 root=tmp_path/"staging"/"ACP-Executor-Isolation-Lab";root.mkdir(parents=True)
 assert validate_probe_root(str(root))==root.resolve()
 assert run_probe(root=str(root))==0
 assert PROBE_ID.endswith(".v1")

def test_probe_rejects_real_project_like_path(tmp_path):
 root=tmp_path/"Active Projects"/"agent-control-plane";root.mkdir(parents=True)
 with pytest.raises(AuthorityValidationError,match="disposable"):
  run_probe(root=str(root))

def test_probe_rejects_unbounded_hold(tmp_path):
 root=tmp_path/"staging"/"ACP-Executor-Isolation-Lab";root.mkdir(parents=True)
 with pytest.raises(AuthorityValidationError,match="between 0 and 30"):
  run_probe(root=str(root),hold_seconds=31)
