from pathlib import Path
S=Path(__file__).parents[1]/"scripts"/"verify_disposable_service_dacl_tamper_surface.ps1"
def src(): return S.read_text()
def test_read_only_service_dacl_query():
 s=src(); assert "sc.exe sdshow" in s; assert "sdset" not in s; assert "Start-Service" not in s
def test_dangerous_tokens_checked():
 s=src()
 for token in ("DC","RP","WP","DT","SD","WD","WO"): assert f'"{token}"' in s
def test_ordinary_principals_checked():
 s=src(); assert 'trustee -eq "IU"' in s; assert 'trustee -eq "SU"' in s
def test_no_overclaim():
 s=src(); assert "peer_process_tamper_resistance_verified=$false" in s
