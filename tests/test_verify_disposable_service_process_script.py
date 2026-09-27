from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"verify_disposable_service_process.ps1"
def t():return S.read_text(encoding="utf-8-sig")
def test_verifier_requires_running_nonzero_pid():
 s=t();assert '$svc.State -ne "Running"' in s;assert "ProcessId" in s
def test_verifier_binds_owner_sid_path_and_hash():
 s=t()
 for x in ("GetOwnerSid","process_owner_sid_match","process_path_match","process_hash_match","Get-FileHash"):assert x in s
def test_verifier_is_read_only():
 s=t()
 for x in ("Start-Service","Stop-Service","New-Service","sc.exe delete"):assert x not in s
