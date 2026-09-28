[CmdletBinding()]
param(
 [string]$ServiceName="ACPExecutorLabProbe",
 [string]$ExpectedWorkerName="ACPExecutorLab",
 [string]$ExpectedBinary="$env:ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe",
 [string]$ExpectedSha256="9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4"
)
$ErrorActionPreference="Stop"
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc){throw "service missing"}
$worker=Get-LocalUser -Name $ExpectedWorkerName -ErrorAction Stop
if($svc.State -ne "Running" -or [int]$svc.ProcessId -le 0){throw "service is not running with a process id"}
$pidValue=[int]$svc.ProcessId
$proc=Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue"
if(-not $proc){throw "service process missing"}
$owner=Invoke-CimMethod -InputObject $proc -MethodName GetOwner
$ownerSidResult=Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid
$actualPath=[IO.Path]::GetFullPath($proc.ExecutablePath)
$expectedPath=[IO.Path]::GetFullPath($ExpectedBinary)
$actualHash=(Get-FileHash -LiteralPath $actualPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checks=[ordered]@{
 service_running=($svc.State -eq "Running")
 pid_nonzero=($pidValue -gt 0)
 scm_account_match=($svc.StartName -ieq ".\$ExpectedWorkerName" -or $svc.StartName -ieq "$env:COMPUTERNAME\$ExpectedWorkerName")
 process_owner_match=("$($owner.Domain)\$($owner.User)" -ieq "$env:COMPUTERNAME\$ExpectedWorkerName")
 process_owner_sid_match=($ownerSidResult.Sid -eq $worker.SID.Value)
 process_path_match=($actualPath -ieq $expectedPath)
 process_hash_match=($actualHash -eq $ExpectedSha256)
}
[pscustomobject]@{
 schema_version="agent-control-plane.disposable-service-process-identity.v1"
 service_name=$svc.Name
 service_state=$svc.State
 process_id=$pidValue
 scm_start_name=$svc.StartName
 process_owner="$($owner.Domain)\$($owner.User)"
 process_owner_sid=$ownerSidResult.Sid
 expected_worker_sid=$worker.SID.Value
 process_path=$actualPath
 process_sha256=$actualHash
 checks=$checks
 verified=(-not($checks.Values -contains $false))
}|ConvertTo-Json -Depth 6
