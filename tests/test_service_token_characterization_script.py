from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"characterize_disposable_service_token.ps1"
def test_characterizer_never_mislabels_observer_token():
 s=S.read_text(); assert "observer_privileges_not_service_evidence=$true" in s; assert "live_service_token_privileges_observed=$false" in s; assert "minimal_service_token_verified=$false" in s
def test_characterizer_is_read_only():
 s=S.read_text(); assert "sc.exe qprivs" in s; assert "Start-Service" not in s; assert "Stop-Service" not in s; assert "privs $ServiceName/" not in s
