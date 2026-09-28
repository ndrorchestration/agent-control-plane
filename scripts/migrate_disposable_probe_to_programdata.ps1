[CmdletBinding()]
param(
 [string]$ServiceName="ACPExecutorLabProbe",
 [string]$WorkerName="ACPExecutorLab",
 [string]$SourceProbe="$env:USERPROFILE\Desktop\NDR-Ecosystem\staging\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe",
 [string]$DestinationRoot="$env:ProgramData\NDR\ACP-Executor-Isolation-Lab",
 [string]$ExpectedSha256="9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4"
)
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
$expectedRoot=[IO.Path]::GetFullPath((Join-Path $env:ProgramData "NDR\ACP-Executor-Isolation-Lab"))
$actualRoot=[IO.Path]::GetFullPath($DestinationRoot)
if($actualRoot -ine $expectedRoot){throw "destination must be exact disposable ProgramData lab"}
$source=[IO.Path]::GetFullPath($SourceProbe)
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "source probe missing"}
$sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
if($sourceHash -ne $ExpectedSha256){throw "source probe hash mismatch"}
$worker=Get-LocalUser -Name $WorkerName -ErrorAction Stop
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc){throw "service missing"}
if($svc.State -ne "Stopped"){throw "service must be stopped before migration"}
New-Item -ItemType Directory -Path $actualRoot -Force | Out-Null
$dest=Join-Path $actualRoot "ACPExecutorLabProbe.exe"
Copy-Item -LiteralPath $source -Destination $dest -Force
$destHash=(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
if($destHash -ne $ExpectedSha256){throw "destination probe hash mismatch"}
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$inherit=[Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
$prop=[Security.AccessControl.PropagationFlags]::None
$allow=[Security.AccessControl.AccessControlType]::Allow
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("SYSTEM","FullControl",$inherit,$prop,$allow)))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("BUILTIN\Administrators","FullControl",$inherit,$prop,$allow)))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($worker.SID,"ReadAndExecute",$inherit,$prop,$allow)))
Set-Acl -LiteralPath $actualRoot -AclObject $acl
sc.exe config $ServiceName binPath= ('"'+$dest+'"') | Out-Null
if($LASTEXITCODE -ne 0){throw "SCM binary path update failed"}
$verify=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
$rules=(Get-Acl -LiteralPath $actualRoot).Access
$workerRule=$rules|Where-Object{try{$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $worker.SID.Value}catch{$false}}
$checks=[ordered]@{
 destination_hash_match=((Get-FileHash $dest -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedSha256)
 service_stopped=($verify.State -eq "Stopped")
 service_manual=($verify.StartMode -eq "Manual")
 service_account_match=($verify.StartName -ieq ".\$WorkerName" -or $verify.StartName -ieq "$env:COMPUTERNAME\$WorkerName")
 service_path_match=($verify.PathName.Trim('"') -ieq $dest)
 worker_read_execute=($null -ne $workerRule -and (($workerRule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::ReadAndExecute) -ne 0))
}
[pscustomobject]@{schema_version="agent-control-plane.programdata-probe-migration.v1";destination=$dest;binary_sha256=$destHash;checks=$checks;verified=(-not($checks.Values -contains $false))}|ConvertTo-Json -Depth 5
