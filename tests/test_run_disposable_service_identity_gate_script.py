from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"run_disposable_service_identity_gate.ps1"
def t():return S.read_text(encoding="utf-8-sig")
def test_gate_requires_admin_manual_and_stopped():
 s=t();assert "Administrator PowerShell required" in s;assert '$svc.StartMode -ne "Manual"' in s;assert '$svc.State -ne "Stopped"' in s
def test_gate_always_stops_service():
 s=t();assert "finally" in s;assert "Stop-Service" in s;assert "failed to return to Stopped" in s
def test_gate_calls_read_only_identity_verifier():
 assert "verify_disposable_service_process.ps1" in t()
