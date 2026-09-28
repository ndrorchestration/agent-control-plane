from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"ACPExecutorTokenProbe.cs"
def src(): return S.read_text()
def test_self_token_only_and_fixed_evidence_path():
 s=src(); assert "OpenProcessToken(Process.GetCurrentProcess().Handle" in s; assert "token-evidence.json" in s; assert "Win32_Process" not in s
def test_no_network_or_repo_access():
 s=src(); assert "System.Net" not in s; assert "Http" not in s; assert "NDR-Ecosystem" not in s; assert "Git" not in s
def test_service_identity_unchanged():
 s=src(); assert 'ServiceName = "ACPExecutorLabProbe"' in s; assert "CanStop = true" in s
