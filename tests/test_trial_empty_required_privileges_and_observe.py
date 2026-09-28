from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"trial_empty_required_privileges_and_observe.ps1"
def src(): return S.read_text()
def test_snapshots_and_restores_required_privileges():
 s=src(); assert "before_required_privileges" in s; assert "finally" in s; assert "sc.exe privs $ServiceName $arg" in s or "sc.exe privs $ServiceName /" in s
def test_uses_direct_token_observer():
 s=src(); assert "observe_disposable_service_token.ps1" in s
def test_exact_disposable_scope():
 s=src(); assert 'ServiceName -ne "ACPExecutorLabProbe"' in s; assert "service must begin stopped" in s
