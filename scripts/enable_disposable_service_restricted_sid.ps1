[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only the disposable probe service is allowed"}
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc){throw "service missing"}
if($svc.State -ne "Stopped"){throw "service must be stopped"}
if($svc.StartMode -ne "Manual"){throw "service must remain manual-start"}
if($svc.StartName -notmatch '(^|\\)ACPExecutorLab$'){throw "unexpected service account"}
$out=& sc.exe sidtype $ServiceName restricted 2>&1
if($LASTEXITCODE -ne 0){throw "failed to set restricted service SID: $out"}
$q=& sc.exe qsidtype $ServiceName 2>&1
$verified=($LASTEXITCODE -eq 0 -and ($q -join "`n") -match 'SERVICE_SID_TYPE:\s+RESTRICTED')
[pscustomobject]@{schema_version="agent-control-plane.disposable-service-sid-isolation.v1";service_name=$ServiceName;service_state=$svc.State;service_account=$svc.StartName;service_sid_type="RESTRICTED";verified=$verified}|ConvertTo-Json
if(-not $verified){throw "restricted service SID verification failed"}
