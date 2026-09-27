import sys
from pathlib import Path
from agent_control_plane.windows_scm_probe_launch import DisposableProbeLaunchSpec

def test_launch_spec_is_explicit_and_hashable(tmp_path):
 src=tmp_path/"src";m=src/"agent_control_plane";m.mkdir(parents=True);(m/"windows_scm_identity_probe.py").write_text("# probe")
 lab=tmp_path/"staging"/"ACP-Executor-Isolation-Lab";lab.mkdir(parents=True)
 s=DisposableProbeLaunchSpec(sys.executable,str(src),str(lab))
 assert s.argv()[1]=="-I"
 assert len(s.content_sha256())==64
 assert "--root" in s.argv()
