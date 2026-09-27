[CmdletBinding()]
param(
    [string]$LabRoot = "$env:USERPROFILE\Desktop\NDR-Ecosystem\staging\ACP-Executor-Isolation-Lab",
    [string]$WorkerName = "ACPExecutorLab",
    [switch]$Apply
)
$ErrorActionPreference = "Stop"
$paths = [ordered]@{
    repository = Join-Path $LabRoot "repository"
    authorization = Join-Path $LabRoot "authorization"
    journal = Join-Path $LabRoot "journal"
    rollback = Join-Path $LabRoot "rollback"
}
function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
foreach ($path in $paths.Values) { New-Item -ItemType Directory -Force -Path $path | Out-Null }
$forbiddenRoots = @(
    (Join-Path $env:USERPROFILE "Desktop\DGAF & Governance"),
    (Join-Path $env:USERPROFILE "Desktop\Aetherwake"),
    (Join-Path $env:USERPROFILE "Desktop\NDR-Ecosystem\Active Projects")
) | ForEach-Object { [IO.Path]::GetFullPath($_) }
$labResolved = [IO.Path]::GetFullPath($LabRoot)
foreach ($forbidden in $forbiddenRoots) {
    if ($labResolved.StartsWith($forbidden, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Lab root must not be inside a real project tree: $forbidden"
    }
}
$worker = Get-LocalUser -Name $WorkerName -ErrorAction SilentlyContinue
$plan = [ordered]@{
    schema_version = "agent-control-plane.executor-isolation-lab-plan.v1"
    lab_root = $labResolved
    worker_name = $WorkerName
    apply_requested = [bool]$Apply
    current_process_is_administrator = (Test-IsAdministrator)
    worker_exists = [bool]$worker
    paths = $paths
    real_project_roots_explicitly_excluded = $forbiddenRoots
    intended_controls = @(
        "dedicated non-interactive local worker identity",
        "worker access limited to disposable lab paths",
        "separate ACL descriptors for repository/auth/journal/rollback",
        "no grants to DGAF/Aetherwake/Active Projects",
        "read-only post-setup evidence audit"
    )
}
if (-not $Apply) { $plan | ConvertTo-Json -Depth 8; exit 0 }
if (-not (Test-IsAdministrator)) { throw "APPLY_REQUIRES_ELEVATED_OPERATOR" }
if (-not $worker) { throw "WORKER_IDENTITY_MUST_BE_CREATED_BY_EXPLICIT_ELEVATED_OPERATOR_STEP" }
$account = "$env:COMPUTERNAME\$WorkerName"
foreach ($entry in $paths.GetEnumerator()) {
    $path = $entry.Value
    & icacls $path /inheritance:r | Out-Null
    & icacls $path /grant:r "${account}:(OI)(CI)M" | Out-Null
    & icacls $path /grant:r "SYSTEM:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed for $path" }
}
$plan.applied = $true
$plan | ConvertTo-Json -Depth 8
