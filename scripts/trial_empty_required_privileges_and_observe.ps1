[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only disposable probe allowed"}
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc -or $svc.State -ne "Stopped"){throw "service must begin stopped"}
$beforeText=(& sc.exe qprivs $ServiceName 2>&1)-join "`n"
$before=@()
foreach($line in ($beforeText -split "`r?`n")){if($line -match '^\s+(Se\w+Privilege)\s*$'){$before += $Matches[1]}}
& sc.exe privs $ServiceName / | Out-Null
if($LASTEXITCODE -ne 0){throw "failed to configure empty required privileges"}
try {
 $afterText=(& sc.exe qprivs $ServiceName 2>&1)-join "`n"
 $after=@()
 foreach($line in ($afterText -split "`r?`n")){if($line -match '^\s+(Se\w+Privilege)\s*$'){$after += $Matches[1]}}
 if($after.Count -ne 0){throw "required privileges were not cleared"}
 $obs=& "$PSScriptRoot\observe_disposable_service_token.ps1" | Out-String
 [pscustomobject]@{
  schema_version="agent-control-plane.required-privileges-empty-bounded-trial.v1"
  before_required_privileges=$before
  after_required_privileges=$after
  token_observation_json=$obs.Trim()
  trial_completed=$true
 }|ConvertTo-Json -Depth 8
} finally {
 if($before.Count -gt 0){
   $arg=($before -join "/")
   & sc.exe privs $ServiceName $arg | Out-Null
 } else {
   & sc.exe privs $ServiceName / | Out-Null
 }
}
$final=(& sc.exe qprivs $ServiceName 2>&1)-join "`n"
[pscustomobject]@{service_name=$ServiceName;required_privileges_restored_text=$final;restored=$true}|ConvertTo-Json -Depth 4
