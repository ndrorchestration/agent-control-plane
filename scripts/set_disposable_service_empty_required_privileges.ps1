[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only disposable probe allowed"}
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc){throw "service missing"}
if($svc.State -ne "Stopped"){throw "service must begin stopped"}
if($svc.StartMode -ne "Manual"){throw "service must remain manual-start"}
if($svc.StartName -notmatch '(^|\\)ACPExecutorLab$'){throw "unexpected service account"}
$sidText=(& sc.exe qsidtype $ServiceName 2>&1)-join "`n"
if($sidText -notmatch 'SERVICE_SID_TYPE:\s+RESTRICTED'){throw "restricted service SID required"}
$before=(& sc.exe qprivs $ServiceName 2>&1)-join "`n"
# sc.exe privs <service> / clears the required-privileges MULTI_SZ.
$out=& sc.exe privs $ServiceName / 2>&1
if($LASTEXITCODE -ne 0){throw "failed to set empty required privileges: $out"}
$after=(& sc.exe qprivs $ServiceName 2>&1)-join "`n"
$explicit=@()
foreach($line in ($after -split "`r?`n")){if($line -match '^\s+(Se\w+Privilege)\s*$'){$explicit += $Matches[1]}}
[pscustomobject]@{
 schema_version="agent-control-plane.required-privileges-empty-candidate.v1"
 service_name=$ServiceName
 service_state=$svc.State
 service_sid_type="RESTRICTED"
 before_qprivs=$before
 after_qprivs=$after
 explicit_required_privileges=$explicit
 explicit_required_privilege_count=$explicit.Count
 configured_empty=($explicit.Count -eq 0)
 live_compatibility_verified=$false
 minimal_service_token_verified=$false
}|ConvertTo-Json -Depth 6
