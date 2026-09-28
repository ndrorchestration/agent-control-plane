[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc -or $svc.State -ne "Running" -or [int]$svc.ProcessId -le 0){throw "service must be running"}
$pidValue=[int]$svc.ProcessId
$who=(& whoami.exe /priv 2>&1) -join "`n"
# whoami reports this observer process, not the service. Never promote it as service-token evidence.
$servicePrivs=(& sc.exe qprivs $ServiceName 2>&1) -join "`n"
$configured=@()
foreach($line in ($servicePrivs -split "`r?`n")){if($line -match '^\s+(Se\w+Privilege)\s*$'){$configured += $Matches[1]}}
[pscustomobject]@{
 schema_version="agent-control-plane.service-token-characterization.v1"
 service_name=$ServiceName
 service_pid=$pidValue
 configured_required_privileges=$configured
 configured_required_privilege_count=$configured.Count
 live_service_token_privileges_observed=$false
 observer_privileges_not_service_evidence=$true
 minimal_service_token_verified=$false
}|ConvertTo-Json -Depth 5
