[CmdletBinding()]
param([string]$WorkerName="ACPExecutorLab")
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
$worker=Get-LocalUser -Name $WorkerName -ErrorAction Stop
$sid=$worker.SID.Value
$tmp=Join-Path $env:TEMP ("acp-secpol-"+[guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$cfg=Join-Path $tmp "rights.inf"; $verifyCfg=Join-Path $tmp "verify.inf"; $db=Join-Path $tmp "rights.sdb"
function Get-ServiceLogonMembers([string]$Path) {
 $line=Get-Content -LiteralPath $Path | Where-Object {$_ -match '^SeServiceLogonRight\s*='} | Select-Object -First 1
 if(-not $line){return @()}
 return @(($line -split "=",2)[1].Split(",")|ForEach-Object{$_.Trim().TrimStart("*")}|Where-Object{$_})
}
try {
 secedit.exe /export /cfg $cfg /areas USER_RIGHTS | Out-Null
 if($LASTEXITCODE -ne 0 -or -not(Test-Path $cfg)){throw "secedit initial export failed"}
 $lines=Get-Content -LiteralPath $cfg
 $members=@(Get-ServiceLogonMembers $cfg)
 $already=$members -contains $sid
 if(-not $already){
   $rawMembers=@()
   $existing=$lines|Where-Object{$_ -match '^SeServiceLogonRight\s*='}|Select-Object -First 1
   if($existing){$rawMembers=@(($existing -split "=",2)[1].Split(",")|ForEach-Object{$_.Trim()}|Where-Object{$_})}
   $newLine="SeServiceLogonRight = "+((@($rawMembers)+("*"+$sid)) -join ",")
   if($existing){$lines=$lines|ForEach-Object{if($_ -eq $existing){$newLine}else{$_}}}else{$lines+=$newLine}
   Set-Content -LiteralPath $cfg -Value $lines -Encoding Unicode
   secedit.exe /configure /db $db /cfg $cfg /areas USER_RIGHTS | Out-Null
   if($LASTEXITCODE -ne 0){throw "secedit configure failed"}
 }
 secedit.exe /export /cfg $verifyCfg /areas USER_RIGHTS | Out-Null
 if($LASTEXITCODE -ne 0 -or -not(Test-Path $verifyCfg)){throw "secedit verification export failed"}
 $verifiedMembers=@(Get-ServiceLogonMembers $verifyCfg)
 $verified=$verifiedMembers -contains $sid
 [pscustomobject]@{worker=$WorkerName;worker_sid=$sid;right="SeServiceLogonRight";already_present=$already;verified=[bool]$verified}|ConvertTo-Json
 if(-not $verified){throw "service logon right verification failed"}
} finally {Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue}
