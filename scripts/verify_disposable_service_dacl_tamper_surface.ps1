[CmdletBinding()]
param([string]$ServiceName="ACPExecutorLabProbe")
$ErrorActionPreference="Stop"
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only disposable probe allowed"}
$raw=(& sc.exe sdshow $ServiceName 2>&1)-join "`n"
if($LASTEXITCODE -ne 0){throw "service DACL query failed"}
if($raw -notmatch '(D:\(.*\))'){throw "service DACL missing"}
$dacl=$Matches[1]
$aces=[regex]::Matches($dacl,'\(A;;([^;]*);;;([^\)]+)\)')
$rows=@()
foreach($ace in $aces){
  $rights=$ace.Groups[1].Value
  $trustee=$ace.Groups[2].Value
  $dangerous=@()
  foreach($r in @("DC","RP","WP","DT","SD","WD","WO")){
    if($rights -match [regex]::Escape($r)){$dangerous += $r}
  }
  $rows += [pscustomobject]@{
    trustee=$trustee
    rights=$rights
    dangerous_right_tokens=$dangerous
    dangerous_right_count=$dangerous.Count
  }
}
$iu=@($rows|Where-Object trustee -eq "IU")
$su=@($rows|Where-Object trustee -eq "SU")
$ba=@($rows|Where-Object trustee -eq "BA")
$sy=@($rows|Where-Object trustee -eq "SY")
$ordinarySafe=(
  $iu.Count -ge 1 -and $su.Count -ge 1 -and
  (@($iu|Where-Object dangerous_right_count -gt 0).Count -eq 0) -and
  (@($su|Where-Object dangerous_right_count -gt 0).Count -eq 0)
)
[pscustomobject]@{
 schema_version="agent-control-plane.service-dacl-tamper-surface.v1"
 service_name=$ServiceName
 sddl=$dacl
 aces=$rows
 interactive_user_dangerous_service_control_absent=$ordinarySafe
 administrators_present=($ba.Count -ge 1)
 system_present=($sy.Count -ge 1)
 peer_service_control_tamper_surface_reduced=($ordinarySafe -and $ba.Count -ge 1 -and $sy.Count -ge 1)
 peer_process_tamper_resistance_verified=$false
}|ConvertTo-Json -Depth 7
