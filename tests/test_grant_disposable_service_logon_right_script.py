from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"grant_disposable_service_logon_right.ps1"
def t():return S.read_text(encoding="utf-8-sig")
def test_exact_right_and_worker_sid(): s=t();assert "SeServiceLogonRight" in s;assert "Get-LocalUser" in s;assert "$worker.SID.Value" in s
def test_requires_admin_and_fresh_verification_export(): s=t();assert "Administrator PowerShell required" in s;assert "verify.inf" in s;assert "secedit verification export failed" in s
def test_normalizes_star_sid_form(): assert 'TrimStart("*")' in t()
def test_no_other_rights_or_groups(): s=t();assert "SeDebugPrivilege" not in s;assert "Add-LocalGroupMember" not in s;assert "Administrators" not in s
