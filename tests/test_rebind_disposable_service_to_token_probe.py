from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"rebind_disposable_service_to_token_probe.ps1"
def src(): return S.read_text()
def test_requires_exact_disposable_preconditions():
 s=src(); assert 'ServiceName -ne "ACPExecutorLabProbe"' in s; assert "service must be stopped" in s; assert "service must remain manual-start" in s; assert "restricted service SID required" in s
def test_hash_binds_both_old_and_new_and_backup():
 s=src(); assert "new token probe hash mismatch" in s; assert "current probe hash mismatch" in s; assert "backup hash mismatch" in s
def test_no_start_or_account_change():
 s=src(); assert "Start-Service" not in s; assert "sc.exe config" not in s; assert "New-Service" not in s
def test_fail_closed_restore_on_install_hash_failure():
 s=src(); assert "Copy-Item -LiteralPath $Backup -Destination $Destination -Force" in s
