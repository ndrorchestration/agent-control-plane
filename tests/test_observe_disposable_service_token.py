from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"observe_disposable_service_token.ps1"
def src(): return S.read_text()
def test_direct_service_pid_token_observation():
 s=src(); assert "OpenProcessToken(p.Handle,TOKEN_QUERY" in s; assert "GetTokenInformation" in s; assert "LookupPrivilegeName" in s
def test_exact_identity_binding_before_token_claim():
 s=src(); assert "service process SID mismatch" in s; assert "service process path mismatch" in s; assert "service process hash mismatch" in s
def test_bounded_and_restores_stopped():
 s=src(); assert "Start-Service" in s; assert "finally" in s; assert "Stop-Service" in s; assert "service failed to return to Stopped" in s
def test_no_binary_swap_or_acl_mutation():
 s=src(); assert "Copy-Item" not in s; assert "Set-Acl" not in s; assert "sc.exe config" not in s
def test_does_not_overclaim_minimal_token():
 s=src(); assert "live_service_token_privileges_observed=$true" in s; assert "minimal_service_token_verified=$false" in s
