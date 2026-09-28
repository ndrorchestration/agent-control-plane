[CmdletBinding()]
param(
 [string]$ServiceName="ACPExecutorLabProbe",
 [string]$TokenProbeSource="$env:USERPROFILE\Desktop\NDR-Ecosystem\staging\ACP-Executor-Isolation-Lab\ACPExecutorTokenProbe.exe",
 [string]$InstalledBinary="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe",
 [string]$BackupBinary="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.identity-backup.exe",
 [string]$EvidencePath="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\token-evidence\token-evidence.json",
 [string]$ExpectedTokenSha256="357c12de943a18bad6f6f6793a66257c4b388b23026f883636e47bc453b04d25",
 [string]$ExpectedIdentitySha256="9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4"
)
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
if((Get-FileHash -LiteralPath $InstalledBinary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedIdentitySha256){throw "installed identity probe hash mismatch"}
if((Get-FileHash -LiteralPath $TokenProbeSource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedTokenSha256){throw "token probe source hash mismatch"}
$evidenceDir=Split-Path -Parent $EvidencePath
$expectedEvidenceDir="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\token-evidence"
if([IO.Path]::GetFullPath($evidenceDir) -ine [IO.Path]::GetFullPath($expectedEvidenceDir)){throw "unexpected token evidence directory"}
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
$servicePrincipal=New-Object Security.Principal.NTAccount("NT SERVICE",$ServiceName)
$serviceSid=$servicePrincipal.Translate([Security.Principal.SecurityIdentifier])
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$inherit=[Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
$prop=[Security.AccessControl.PropagationFlags]::None
$allow=[Security.AccessControl.AccessControlType]::Allow
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("SYSTEM","FullControl",$inherit,$prop,$allow)))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("BUILTIN\Administrators","FullControl",$inherit,$prop,$allow)))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($serviceSid,"Modify",$inherit,$prop,$allow)))
Set-Acl -LiteralPath $evidenceDir -AclObject $acl
$serviceAcl=(Get-Acl -LiteralPath $evidenceDir).Access | Where-Object { try {$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $serviceSid.Value -and $_.AccessControlType -eq "Allow"} catch {$false} }
if(-not $serviceAcl){throw "service SID evidence ACL verification failed"}
if(Test-Path -LiteralPath $EvidencePath){Remove-Item -LiteralPath $EvidencePath -Force}
Copy-Item -LiteralPath $InstalledBinary -Destination $BackupBinary -Force
if((Get-FileHash -LiteralPath $BackupBinary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedIdentitySha256){throw "identity backup hash mismatch"}
$restored=$false
try {
 Copy-Item -LiteralPath $TokenProbeSource -Destination $InstalledBinary -Force
 if((Get-FileHash -LiteralPath $InstalledBinary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedTokenSha256){throw "installed token probe hash mismatch"}
 Start-Service -Name $ServiceName
 $deadline=(Get-Date).AddSeconds(10)
 do{$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"; if($svc.State -eq "Running"){break}; Start-Sleep -Milliseconds 200}while((Get-Date)-lt $deadline)
 if($svc.State -ne "Running"){throw "token probe service did not reach Running"}
 $pidValue=[int]$svc.ProcessId
 $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue"
 if(-not $proc){throw "token probe process missing"}
 $ownerSid=(Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid).Sid
 $worker=(Get-LocalUser ACPExecutorLab).SID.Value
 if($ownerSid -ne $worker){throw "token probe process SID mismatch"}
 $deadline=(Get-Date).AddSeconds(5)
 do{if(Test-Path -LiteralPath $EvidencePath){break};Start-Sleep -Milliseconds 100}while((Get-Date)-lt $deadline)
 if(-not(Test-Path -LiteralPath $EvidencePath -PathType Leaf)){throw "token evidence was not produced"}
 $e=Get-Content -LiteralPath $EvidencePath -Raw | ConvertFrom-Json
 if($e.schema_version -ne "agent-control-plane.self-token-evidence.v1"){throw "unexpected token evidence schema"}
 if([int]$e.pid -ne $pidValue){throw "token evidence PID mismatch"}
 $privs=@($e.privileges|ForEach-Object{$_.name})
 $result=[ordered]@{
   schema_version="agent-control-plane.bounded-token-probe-cycle.v1"
   service_name=$ServiceName
   service_pid=$pidValue
   process_owner_sid=$ownerSid
   expected_worker_sid=$worker
   service_sid_type="RESTRICTED"
   token_probe_sha256=$ExpectedTokenSha256
   privilege_count=$privs.Count
   privilege_names=$privs
   live_service_token_privileges_observed=$true
   minimal_service_token_verified=$false
 }
} finally {
 Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
 $deadline=(Get-Date).AddSeconds(10)
 do{$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'";if($svc.State -eq "Stopped"){break};Start-Sleep -Milliseconds 200}while((Get-Date)-lt $deadline)
 Copy-Item -LiteralPath $BackupBinary -Destination $InstalledBinary -Force
 $restored=((Get-FileHash -LiteralPath $InstalledBinary -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedIdentitySha256)
}
if(-not $restored){throw "identity probe restore verification failed"}
$final=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
$result["final_state"]=$final.State
$result["identity_probe_restored"]=$restored
$result["restored_sha256"]=(Get-FileHash -LiteralPath $InstalledBinary -Algorithm SHA256).Hash.ToLowerInvariant()
$result["verified"]=($result.live_service_token_privileges_observed -and $restored -and $final.State -eq "Stopped")
[pscustomobject]$result|ConvertTo-Json -Depth 6
