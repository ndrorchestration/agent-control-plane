from pathlib import Path
R=Path(__file__).parents[1]/"scripts"/"enable_disposable_service_restricted_sid.ps1"
V=Path(__file__).parents[1]/"scripts"/"verify_disposable_service_sid.ps1"
def test_operator_gate_is_disposable_only():
 s=R.read_text(); assert "Administrator PowerShell required" in s; assert 'ServiceName -ne "ACPExecutorLabProbe"' in s; assert 'service must be stopped' in s; assert 'service must remain manual-start' in s
def test_restricted_sid_only_mutation():
 s=R.read_text(); assert "sc.exe sidtype $ServiceName restricted" in s; assert "Start-Service" not in s; assert "New-Service" not in s; assert "sc.exe config" not in s
def test_fail_closed_readback():
 s=R.read_text(); assert "SERVICE_SID_TYPE" in s and "RESTRICTED" in s; assert "restricted service SID verification failed" in s
def test_verifier_is_read_only():
 s=V.read_text(); assert "sc.exe qsidtype" in s; assert "sidtype $ServiceName restricted" not in s; assert "Start-Service" not in s
