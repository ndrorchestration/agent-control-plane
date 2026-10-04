param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$createdProcessKey = $false
$bstr = [IntPtr]::Zero

try {
    if (-not $env:GEMINI_API_KEY) {
        $secure = Read-Host "Enter dedicated CEP Gemini API key" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $createdProcessKey = $true
    }

    & $Python "scripts/run_gemini_live_ab.py"
    exit $LASTEXITCODE
}
finally {
    if ($createdProcessKey) {
        Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
    }
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}
