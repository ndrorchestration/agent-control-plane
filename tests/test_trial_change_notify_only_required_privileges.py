from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"trial_change_notify_only_required_privileges.ps1"
def src(): return S.read_text()
def test_explicit_single_privilege():
 s=src(); assert "sc.exe privs $ServiceName SeChangeNotifyPrivilege" in s
def test_verifies_exact_config():
 s=src(); assert "required privilege configuration mismatch" in s
def test_runs_direct_token_observer():
 s=src(); assert "observe_disposable_service_token.ps1" in s
def test_restores_previous_configuration():
 s=src(); assert "finally" in s and "sc.exe privs $ServiceName $arg" in s
def test_does_not_overclaim():
 s=src(); assert "minimal_service_token_verified=$false" in s
def test_qprivs_parser_accepts_inline_privilege_tokens():
 s=src(); assert "Parse-RequiredPrivileges" in s; assert "[regex]::Matches($line,'Se\\w+Privilege')" in s

def test_single_privilege_result_forced_to_array():
 s=src()
 assert "$before=@(Parse-RequiredPrivileges $beforeText)" in s
 assert "$configured=@(Parse-RequiredPrivileges $configuredText)" in s