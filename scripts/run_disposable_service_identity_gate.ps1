[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc){throw "service missing"}
if($svc.StartMode -ne "Manual"){throw "service is not manual-start"}
if($svc.State -ne "Stopped"){throw "service must begin stopped"}
Start-Service -Name $ServiceName
try {
  $deadline=(Get-Date).AddSeconds(10)
  do {$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'";if($svc.State -eq "Running"){break};Start-Sleep -Milliseconds 200} while((Get-Date)-lt $deadline)
  if($svc.State -ne "Running"){throw "service did not reach Running"}
  & "$PSScriptRoot\verify_disposable_service_process.ps1"
  if($LASTEXITCODE){throw "process verifier failed"}
} finally {
  Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
}
$final=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if($final.State -ne "Stopped"){throw "service failed to return to Stopped"}
[pscustomobject]@{service_name=$ServiceName;final_state=$final.State;bounded_start_stop_completed=$true}|ConvertTo-Json
