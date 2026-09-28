from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"migrate_disposable_probe_to_programdata.ps1"
def t(): return S.read_text(encoding="utf-8-sig")
def test_exact_programdata_scope_and_hash_binding():
 s=t(); assert 'ProgramData "NDR\\ACP-Executor-Isolation-Lab"' in s; assert "source probe hash mismatch" in s; assert "destination probe hash mismatch" in s
def test_narrow_acl():
 s=t(); assert '"SYSTEM","FullControl"' in s; assert '"BUILTIN\\Administrators","FullControl"' in s; assert '"ReadAndExecute"' in s; assert "SetAccessRuleProtection($true,$false)" in s
def test_only_rebinds_existing_stopped_service():
 s=t(); assert 'service must be stopped before migration' in s; assert "sc.exe config" in s; assert "New-Service" not in s; assert "Start-Service" not in s
