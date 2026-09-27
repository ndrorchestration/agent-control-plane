from pathlib import Path

SCRIPT=Path(__file__).parents[1]/"scripts"/"install_disposable_scm_probe.ps1"

def text(): return SCRIPT.read_text(encoding="utf-8-sig")

def test_operator_script_is_manual_only_and_never_starts_service():
 s=text()
 assert "-StartupType Manual" in s
 assert "Start-Service" not in s
 assert "-StartupType Automatic" not in s

def test_operator_script_prompts_securely_and_has_no_literal_secret():
 s=text()
 assert 'Read-Host "ACPExecutorLab temporary password" -AsSecureString' in s
 assert "operator-transient:ACPExecutorLab" not in s
 assert "password=" not in s.lower()

def test_operator_script_hash_binds_and_rolls_back_failed_verification():
 s=text()
 assert "Get-FileHash" in s
 assert "Probe SHA-256 mismatch" in s
 assert "sc.exe delete $ServiceName" in s
 assert "Post-install SCM identity verification failed" in s

def test_operator_script_refuses_existing_service_and_outside_lab():
 s=text()
 assert "Service already exists; refusing ambiguous overwrite" in s
 assert "Probe path outside disposable isolation lab" in s
