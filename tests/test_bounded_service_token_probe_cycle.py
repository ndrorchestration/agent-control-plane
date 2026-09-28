from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"run_bounded_service_token_probe_cycle.ps1"
def src(): return S.read_text()
def test_strict_preconditions():
 s=src(); assert "Administrator PowerShell required" in s; assert 'only disposable probe allowed' in s; assert 'service must begin stopped' in s; assert 'restricted service SID required' in s
def test_hash_binds_binaries_and_pid():
 s=src(); assert "installed identity probe hash mismatch" in s; assert "token probe source hash mismatch" in s; assert "token evidence PID mismatch" in s
def test_always_stops_and_restores():
 s=src(); assert "finally" in s; assert "Stop-Service" in s; assert "Copy-Item -LiteralPath $BackupBinary -Destination $InstalledBinary -Force" in s; assert "identity probe restore verification failed" in s
def test_does_not_claim_minimal_token():
 s=src(); assert "minimal_service_token_verified=$false" in s
