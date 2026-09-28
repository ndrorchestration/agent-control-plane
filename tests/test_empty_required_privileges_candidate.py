from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"set_disposable_service_empty_required_privileges.ps1"
def src(): return S.read_text()
def test_scope_and_preconditions():
 s=src(); assert "Administrator PowerShell required" in s; assert 'only disposable probe allowed' in s; assert 'service must begin stopped' in s; assert 'restricted service SID required' in s
def test_only_required_privileges_mutation():
 s=src(); assert "sc.exe privs $ServiceName /" in s; assert "Start-Service" not in s; assert "sc.exe config" not in s; assert "sidtype" in s
def test_no_overclaim():
 s=src(); assert "live_compatibility_verified=$false" in s; assert "minimal_service_token_verified=$false" in s
