[CmdletBinding()]
param(
 [string]$EvidencePath="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\token-evidence.json"
)
$ErrorActionPreference="Stop"
if(-not(Test-Path -LiteralPath $EvidencePath -PathType Leaf)){throw "token evidence missing"}
$j=Get-Content -LiteralPath $EvidencePath -Raw | ConvertFrom-Json
if($j.schema_version -ne "agent-control-plane.self-token-evidence.v1"){throw "unexpected token evidence schema"}
if([int]$j.pid -le 0){throw "invalid token evidence pid"}
$names=@($j.privileges | ForEach-Object {$_.name})
[pscustomobject]@{
 schema_version="agent-control-plane.self-token-evidence-verification.v1"
 evidence_path=$EvidencePath
 pid=[int]$j.pid
 privilege_count=$names.Count
 privilege_names=$names
 live_service_token_privileges_observed=$true
 minimal_service_token_verified=$false
}|ConvertTo-Json -Depth 6
