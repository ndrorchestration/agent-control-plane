from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"grant_disposable_service_logon_right.ps1"
def t():return S.read_text(encoding="utf-8-sig")
def test_accepts_exact_sid_or_exact_local_name():
 s=t(); assert '($members -contains $sid) -or ($members -contains $WorkerName)' in s; assert '($verifiedMembers -contains $sid) -or ($verifiedMembers -contains $WorkerName)' in s
def test_no_substring_account_matching(): assert "-like" not in t()
def test_scope_still_exact_right_only():
 s=t(); assert "SeServiceLogonRight" in s; assert "SeDebugPrivilege" not in s; assert "Add-LocalGroupMember" not in s
