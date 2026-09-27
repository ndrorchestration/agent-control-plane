[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$AuthorizationStorePath,
    [Parameter(Mandatory=$true)][string]$JournalStorePath,
    [Parameter(Mandatory=$true)][string]$RollbackCustodyPath,
    [Parameter(Mandatory=$true)][string]$ExecutablePath,
    [string]$ExpectedWorkerName = "ACPExecutorLab"
)
$ErrorActionPreference = "Stop"
function Resolve-EvidencePath([string]$PathValue) {
    if (-not [System.IO.Path]::IsPathRooted($PathValue)) { throw "All evidence paths must be absolute: $PathValue" }
    return [System.IO.Path]::GetFullPath($PathValue)
}
function Get-IntegrityLevel {
    foreach ($line in (whoami /groups)) { if ($line -match "Mandatory Label\\(.+?)\s+Label") { return $Matches[1].Trim() } }
    return "UNKNOWN"
}
function Get-PathAclEvidence([string]$PathValue) {
    $resolved=Resolve-EvidencePath $PathValue
    $item=if(Test-Path -LiteralPath $resolved){Get-Item -LiteralPath $resolved}else{Get-Item -LiteralPath (Split-Path -Parent $resolved)}
    $acl=Get-Acl -LiteralPath $item.FullName
    $rules=@($acl.Access | ForEach-Object {[ordered]@{identity=$_.IdentityReference.Value;type=$_.AccessControlType.ToString();rights=$_.FileSystemRights.ToString();inherited=$_.IsInherited}})
    [ordered]@{requested_path=$resolved;inspected_path=$item.FullName;owner=$acl.Owner;are_access_rules_protected=$acl.AreAccessRulesProtected;sddl=$acl.Sddl;access_rules=$rules}
}
$repo=Get-PathAclEvidence $RepositoryRoot
$auth=Get-PathAclEvidence $AuthorizationStorePath
$journal=Get-PathAclEvidence $JournalStorePath
$custody=Get-PathAclEvidence $RollbackCustodyPath
$exe=Resolve-EvidencePath $ExecutablePath
if(-not(Test-Path -LiteralPath $exe -PathType Leaf)){throw "Executable does not exist: $exe"}
$worker=Get-LocalUser -Name $ExpectedWorkerName -ErrorAction SilentlyContinue
$workerSid=if($worker){$worker.SID.Value}else{$null}
$workerAccount=if($worker){"$env:COMPUTERNAME\$ExpectedWorkerName"}else{$null}
$adminMember=$false
if($worker){$adminMember=[bool](Get-LocalGroupMember Administrators -ErrorAction SilentlyContinue | Where-Object {$_.SID.Value -eq $workerSid})}
$acls=@($repo,$auth,$journal,$custody)
$protectedCount=@($acls | Where-Object {$_.are_access_rules_protected}).Count
$workerAclCount=0
if($workerSid){foreach($a in $acls){$matched=$false; foreach($rule in $a.access_rules){try{$sid=(New-Object System.Security.Principal.NTAccount($rule.identity)).Translate([System.Security.Principal.SecurityIdentifier]).Value;if($sid -eq $workerSid){$matched=$true}}catch{}};if($matched){$workerAclCount++}}}
$pathDistinct=@($repo.inspected_path,$auth.inspected_path,$journal.inspected_path,$custody.inspected_path | Sort-Object -Unique).Count -eq 4
$aclIsolation=($protectedCount -eq 4 -and $workerAclCount -eq 4 -and $pathDistinct -and -not $adminMember)
$result=[ordered]@{
 schema_version="agent-control-plane.executor-windows-boundary-audit.v1-candidate"
 collected_at_utc=(Get-Date).ToUniversalTime().ToString("o")
 read_only_audit=$true
 audit_process_user=(whoami)
 integrity_level=(Get-IntegrityLevel)
 executable_path=$exe
 executable_sha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
 expected_worker_name=$ExpectedWorkerName
 expected_worker_exists=[bool]$worker
 expected_worker_sid=$workerSid
 expected_worker_is_administrator=$adminMember
 repository=$repo;authorization_store=$auth;journal_store=$journal;rollback_custody=$custody
 paths_distinct=$pathDistinct
 protected_acl_path_count=$protectedCount
 worker_acl_path_count=$workerAclCount
 acl_separation_observed=$aclIsolation
 dedicated_service_identity_verified=$false
 trusted_launcher_identity_verified=$false
 os_isolation_verified=$false
 peer_process_tamper_resistance_verified=$false
 high_assurance_boundary_established=$false
}
$result | ConvertTo-Json -Depth 10
