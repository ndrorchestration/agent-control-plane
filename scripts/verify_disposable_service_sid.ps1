[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only the disposable probe service is allowed"}
$q=& sc.exe qsidtype $ServiceName 2>&1
if($LASTEXITCODE -ne 0){throw "service SID query failed"}
$text=$q -join "`n"
$type=if($text -match 'SERVICE_SID_TYPE:\s+(\w+)'){$Matches[1]}else{"UNKNOWN"}
[pscustomobject]@{schema_version="agent-control-plane.disposable-service-sid-readback.v1";service_name=$ServiceName;service_sid_type=$type;restricted=($type -eq "RESTRICTED")}|ConvertTo-Json
