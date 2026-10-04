from pathlib import Path


SCRIPT = Path("scripts/run_gemini_live_ab.ps1")


def test_windows_launcher_prompts_securely_and_clears_process_key() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert 'Read-Host "Enter dedicated CEP Gemini API key" -AsSecureString' in content
    assert "SecureStringToBSTR" in content
    assert "PtrToStringBSTR" in content
    assert 'Remove-Item Env:GEMINI_API_KEY' in content
    assert "ZeroFreeBSTR" in content
    assert '"scripts/run_gemini_live_ab.py" --send' in content
