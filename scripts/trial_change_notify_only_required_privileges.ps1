[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only disposable probe allowed"}
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc -or $svc.State -ne "Stopped"){throw "service must begin stopped"}
if($svc.StartMode -ne "Manual"){throw "service must remain manual-start"}
if($svc.StartName -notmatch '(^|\\)ACPExecutorLab$'){throw "unexpected service account"}
$sidText=(& sc.exe qsidtype $ServiceName 2>&1)-join "`n"
if($sidText -notmatch 'SERVICE_SID_TYPE:\s+RESTRICTED'){throw "restricted service SID required"}

function Parse-RequiredPrivileges([string]$text) {
  $items=@()
  foreach($line in ($text -split "`r?`n")){
    foreach($m in [regex]::Matches($line,'Se\w+Privilege')){$items += $m.Value}
  }
  return @($items | Select-Object -Unique)
}

$beforeText=(& sc.exe qprivs $ServiceName 2>&1)-join "`n"
$before=@(Parse-RequiredPrivileges $beforeText)

& sc.exe privs $ServiceName SeChangeNotifyPrivilege | Out-Null
if($LASTEXITCODE -ne 0){throw "failed to configure SeChangeNotifyPrivilege-only policy"}

try {
  $configuredText=(& sc.exe qprivs $ServiceName 2>&1)-join "`n"
  $configured=@(Parse-RequiredPrivileges $configuredText)
  if($configured.Count -ne 1 -or $configured[0] -ne "SeChangeNotifyPrivilege"){throw "required privilege configuration mismatch"}

  $obsRaw=& "$PSScriptRoot\observe_disposable_service_token.ps1"
  $obsText=$obsRaw | Out-String
  $jsonBlocks=@()
  $depth=0;$start=-1
  for($i=0;$i -lt $obsText.Length;$i++){
    if($obsText[$i] -eq '{'){if($depth -eq 0){$start=$i};$depth++}
    elseif($obsText[$i] -eq '}'){$depth--;if($depth -eq 0 -and $start -ge 0){$jsonBlocks += $obsText.Substring($start,$i-$start+1);$start=-1}}
  }
  if($jsonBlocks.Count -lt 1){throw "token observation JSON missing"}
  $obs=$jsonBlocks[0] | ConvertFrom-Json
  $names=@($obs.privileges | ForEach-Object {$_.name})
  [pscustomobject]@{
    schema_version="agent-control-plane.required-privileges-change-notify-bounded-trial.v1"
    before_required_privileges=$before
    configured_required_privileges=$configured
    observed_privilege_names=$names
    observed_privilege_count=$names.Count
    only_change_notify_observed=($names.Count -eq 1 -and $names[0] -eq "SeChangeNotifyPrivilege")
    live_service_token_privileges_observed=$obs.live_service_token_privileges_observed
    trial_completed=$true
    minimal_service_token_verified=$false
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
[pscustomobject]@{
 service_name=$ServiceName
 required_privileges_restored_text=$final
 restored=$true
}|ConvertTo-Json -Depth 4
