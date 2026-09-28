from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"verify_self_token_evidence.ps1"
def test_parser_binds_schema_and_pid():
 s=S.read_text(); assert "agent-control-plane.self-token-evidence.v1" in s; assert "invalid token evidence pid" in s
def test_parser_does_not_overclaim_minimal_token():
 s=S.read_text(); assert "live_service_token_privileges_observed=$true" in s; assert "minimal_service_token_verified=$false" in s
def test_parser_is_read_only():
 s=S.read_text(); assert "Set-Content" not in s; assert "Remove-Item" not in s; assert "Start-Service" not in s
