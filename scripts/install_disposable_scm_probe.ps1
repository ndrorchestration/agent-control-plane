[CmdletBinding()]
param(
  [string]$ProbePath = "$env:USERPROFILE\Desktop\NDR-Ecosystem\staging\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe",
  [string]$ExpectedSha256 = "9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4",
  [string]$ServiceName = "ACPExecutorLabProbe",
  [string]$WorkerAccount = ".\ACPExecutorLab"
)
$ErrorActionPreference="Stop"
$expectedRoot=[IO.Path]::GetFullPath("$env:USERPROFILE\Desktop\NDR-Ecosystem\staging\ACP-Executor-Isolation-Lab")
$probe=[IO.Path]::GetFullPath($ProbePath)
if(-not $probe.StartsWith($expectedRoot,[StringComparison]::OrdinalIgnoreCase)){throw "Probe path outside disposable isolation lab"}
if(-not(Test-Path -LiteralPath $probe -PathType Leaf)){throw "Probe executable missing"}
$actual=(Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash.ToLowerInvariant()
if($actual -ne $ExpectedSha256){throw "Probe SHA-256 mismatch: $actual"}
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
$worker=Get-LocalUser ACPExecutorLab -ErrorAction Stop
if(-not $worker.Enabled){throw "ACPExecutorLab is disabled"}
if(Get-Service -Name $ServiceName -ErrorAction SilentlyContinue){throw "Service already exists; refusing ambiguous overwrite"}
$secure=Read-Host "ACPExecutorLab temporary password" -AsSecureString
$bstr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$plain=$null
try {
  $plain=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  $cred=New-Object Management.Automation.PSCredential($WorkerAccount,$secure)
  New-Service -Name $ServiceName -BinaryPathName ('"'+$probe+'"') -Credential $cred -StartupType Manual -DisplayName "ACP Disposable Executor Identity Probe" -Description "Disposable ACP #118 service identity probe; no project execution authority." | Out-Null
} finally {
  if($plain){$plain=$null}
  if($bstr -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)}
}
try {
  $svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
  if(-not $svc){throw "Installed service not readable from CIM"}
  $observedPath=$svc.PathName.Trim('"')
  $checks=[ordered]@{
    name_match=($svc.Name -eq $ServiceName)
    account_match=($svc.StartName -ieq $WorkerAccount -or $svc.StartName -ieq "$env:COMPUTERNAME\ACPExecutorLab")
    path_match=([IO.Path]::GetFullPath($observedPath) -ieq $probe)
    start_mode_match=($svc.StartMode -eq "Manual")
    binary_hash_match=((Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedSha256)
    state_is_stopped=($svc.State -eq "Stopped")
  }
  $ok=-not($checks.Values -contains $false)
  [pscustomobject]@{
    schema_version="agent-control-plane.disposable-scm-install-evidence.v1"
    service_name=$svc.Name
    start_name=$svc.StartName
    path_name=$svc.PathName
    start_mode=$svc.StartMode
    state=$svc.State
    binary_sha256=$actual
    checks=$checks
    verified=$ok
  } | ConvertTo-Json -Depth 6
  if(-not $ok){throw "Post-install SCM identity verification failed"}
} catch {
  sc.exe delete $ServiceName | Out-Null
  throw
}
