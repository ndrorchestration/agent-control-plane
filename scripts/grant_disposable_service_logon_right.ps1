[CmdletBinding()]
param([string]$WorkerName="ACPExecutorLab")
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
$worker=Get-LocalUser -Name $WorkerName -ErrorAction Stop
$sid=$worker.SID.Value
$tmp=Join-Path $env:TEMP ("acp-secpol-"+[guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$cfg=Join-Path $tmp "rights.inf"
$db=Join-Path $tmp "rights.sdb"
try {
 secedit.exe /export /cfg $cfg /areas USER_RIGHTS | Out-Null
 if($LASTEXITCODE -ne 0){throw "secedit export failed"}
 $lines=Get-Content -LiteralPath $cfg
 $prefix="SeServiceLogonRight = "
 $existing=$lines | Where-Object {$_ -like "SeServiceLogonRight*"} | Select-Object -First 1
 $members=@()
 if($existing){$members=($existing -split "=",2)[1].Split(",")|ForEach-Object{$_.Trim()}|Where-Object{$_}}
 $sidToken="*$sid"
 $already=$members -contains $sidToken
 if(-not $already){
   $members=@($members)+$sidToken
   $newLine=$prefix+($members -join ",")
   if($existing){$lines=$lines|ForEach-Object{if($_ -eq $existing){$newLine}else{$_}}}
   else{$lines+= $newLine}
   Set-Content -LiteralPath $cfg -Value $lines -Encoding Unicode
   secedit.exe /configure /db $db /cfg $cfg /areas USER_RIGHTS | Out-Null
   if($LASTEXITCODE -ne 0){throw "secedit configure failed"}
 }
 secedit.exe /export /cfg $cfg /areas USER_RIGHTS | Out-Null
 $verify=(Get-Content $cfg|Where-Object{$_ -like "SeServiceLogonRight*"}|Select-Object -First 1)
 $verified=$verify -and (($verify -split "=",2)[1].Split(",")|ForEach-Object{$_.Trim()}) -contains $sidToken
 [pscustomobject]@{worker=$WorkerName;worker_sid=$sid;right="SeServiceLogonRight";already_present=$already;verified=[bool]$verified}|ConvertTo-Json
 if(-not $verified){throw "service logon right verification failed"}
} finally {Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue}
