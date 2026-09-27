from agent_control_plane.windows_scm_installed_identity import (
 WindowsInstalledServiceIdentity, assess_installed_service_identity, identity_from_cim_record
)

def obs(**kw):
 v=dict(service_name="ACPExecutorLabService",account_name=".\\ACPExecutorLab",binary_path=r"C:\lab\worker.exe",binary_sha256="a"*64,start_mode="Manual",state="Stopped");v.update(kw);return WindowsInstalledServiceIdentity(**v)

def test_exact_identity_matches():
 r=assess_installed_service_identity(obs(),expected_service_name="ACPExecutorLabService",expected_account_name=".\\ACPExecutorLab",expected_binary_path=r"C:\lab\worker.exe",expected_binary_sha256="a"*64)
 assert r.matched and r.reasons==()

def test_wrong_account_fails_closed():
 r=assess_installed_service_identity(obs(account_name="LocalSystem"),expected_service_name="ACPExecutorLabService",expected_account_name=".\\ACPExecutorLab",expected_binary_path=r"C:\lab\worker.exe",expected_binary_sha256="a"*64)
 assert not r.matched and "service account mismatch" in r.reasons

def test_auto_start_fails_bounded_lab_policy():
 r=assess_installed_service_identity(obs(start_mode="Auto"),expected_service_name="ACPExecutorLabService",expected_account_name=".\\ACPExecutorLab",expected_binary_path=r"C:\lab\worker.exe",expected_binary_sha256="a"*64)
 assert not r.matched and "service start mode outside bounded lab policy" in r.reasons

def test_cim_quoted_path_parses_binary_only():
 x=identity_from_cim_record({"Name":"S","StartName":".\\ACPExecutorLab","PathName":'"C:\\lab path\\worker.exe" --service',"StartMode":"Manual","State":"Stopped"},binary_sha256="b"*64)
 assert x.binary_path==r"C:\lab path\worker.exe"
