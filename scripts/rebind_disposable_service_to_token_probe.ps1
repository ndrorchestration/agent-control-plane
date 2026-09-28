[CmdletBinding()]
param(
 [string]$ServiceName="ACPExecutorLabProbe",
 [string]$SourceProbe="$env:USERPROFILE\Desktop\NDR-Ecosystem\staging\ACP-Executor-Isolation-Lab\ACPExecutorTokenProbe.exe",
 [string]$Destination="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe",
 [string]$Backup="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.identity-backup.exe",
 [string]$ExpectedNewSha256="642ca4a7a9569a04ce5512c53ffe004eee7c2ce0b8759872778474607dd8d4b0",
 [string]$ExpectedCurrentSha256="9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4"
)
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only disposable probe allowed"}
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc){throw "service missing"}
if($svc.State -ne "Stopped"){throw "service must be stopped"}
if($svc.StartMode -ne "Manual"){throw "service must remain manual-start"}
if($svc.StartName -notmatch '(^|\\)ACPExecutorLab$'){throw "unexpected service account"}
$sidText=(& sc.exe qsidtype $ServiceName 2>&1)-join "`n"
if($sidText -notmatch 'SERVICE_SID_TYPE:\s+RESTRICTED'){throw "restricted service SID required"}
if(-not(Test-Path -LiteralPath $SourceProbe -PathType Leaf)){throw "new token probe missing"}
if(-not(Test-Path -LiteralPath $Destination -PathType Leaf)){throw "current probe missing"}
$newHash=(Get-FileHash -LiteralPath $SourceProbe -Algorithm SHA256).Hash.ToLowerInvariant()
$oldHash=(Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
if($newHash -ne $ExpectedNewSha256){throw "new token probe hash mismatch"}
if($oldHash -ne $ExpectedCurrentSha256){throw "current probe hash mismatch"}
Copy-Item -LiteralPath $Destination -Destination $Backup -Force
if((Get-FileHash -LiteralPath $Backup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedCurrentSha256){throw "backup hash mismatch"}
Copy-Item -LiteralPath $SourceProbe -Destination $Destination -Force
$installed=(Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
if($installed -ne $ExpectedNewSha256){Copy-Item -LiteralPath $Backup -Destination $Destination -Force; throw "installed token probe hash mismatch"}
[pscustomobject]@{
 schema_version="agent-control-plane.token-probe-rebind.v1"
 service_name=$ServiceName
 service_state=$svc.State
 service_account=$svc.StartName
 service_sid_type="RESTRICTED"
 installed_sha256=$installed
 backup_sha256=(Get-FileHash -LiteralPath $Backup -Algorithm SHA256).Hash.ToLowerInvariant()
 verified=$true
}|ConvertTo-Json -Depth 5
