[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$AuthorizationStorePath,
    [Parameter(Mandatory=$true)][string]$JournalStorePath,
    [Parameter(Mandatory=$true)][string]$RollbackCustodyPath,
    [Parameter(Mandatory=$true)][string]$ExecutablePath
)

$ErrorActionPreference = "Stop"

function Resolve-EvidencePath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue) -eq $false) {
        throw "All evidence paths must be absolute: $PathValue"
    }
    return [System.IO.Path]::GetFullPath($PathValue)
}

function Get-IntegrityLevel {
    $groups = whoami /groups
    foreach ($line in $groups) {
        if ($line -match "Mandatory Label\\(.+?)\s+Label") {
            return $Matches[1].Trim()
        }
    }
    return "UNKNOWN"
}

function Get-PathAclEvidence([string]$PathValue) {
    $resolved = Resolve-EvidencePath $PathValue
    $parent = if (Test-Path -LiteralPath $resolved) {
        Get-Item -LiteralPath $resolved
    } else {
        $parentPath = Split-Path -Parent $resolved
        if (-not (Test-Path -LiteralPath $parentPath)) {
            throw "Evidence path and parent do not exist: $resolved"
        }
        Get-Item -LiteralPath $parentPath
    }
    $acl = Get-Acl -LiteralPath $parent.FullName
    [ordered]@{
        requested_path = $resolved
        inspected_path = $parent.FullName
        owner = $acl.Owner
        are_access_rules_protected = $acl.AreAccessRulesProtected
        sddl = $acl.Sddl
    }
}

$repo = Get-PathAclEvidence $RepositoryRoot
$auth = Get-PathAclEvidence $AuthorizationStorePath
$journal = Get-PathAclEvidence $JournalStorePath
$custody = Get-PathAclEvidence $RollbackCustodyPath
$exe = Resolve-EvidencePath $ExecutablePath

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Executable does not exist: $exe"
}

$aclSddls = @($repo.sddl, $auth.sddl, $journal.sddl, $custody.sddl)
$distinctAclCount = ($aclSddls | Sort-Object -Unique).Count

$result = [ordered]@{
    schema_version = "agent-control-plane.executor-windows-boundary-audit.v0-candidate"
    collected_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    read_only_audit = $true
    user_name = (whoami)
    integrity_level = (Get-IntegrityLevel)
    executable_path = $exe
    executable_sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    repository = $repo
    authorization_store = $auth
    journal_store = $journal
    rollback_custody = $custody
    distinct_acl_descriptor_count = $distinctAclCount
    acl_separation_observed = ($distinctAclCount -eq 4)
    dedicated_service_identity_verified = $false
    trusted_launcher_identity_verified = $false
    os_isolation_verified = $false
    peer_process_tamper_resistance_verified = $false
    high_assurance_boundary_established = $false
}

$result | ConvertTo-Json -Depth 8
