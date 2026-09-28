[CmdletBinding()]
param(
 [string]$ServiceName="ACPExecutorLabProbe",
 [string]$ExpectedWorkerName="ACPExecutorLab",
 [string]$ExpectedBinary="C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe",
 [string]$ExpectedSha256="9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4"
)
$ErrorActionPreference="Stop"
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $admin){throw "Administrator PowerShell required"}
if($ServiceName -ne "ACPExecutorLabProbe"){throw "only disposable probe allowed"}
$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if(-not $svc){throw "service missing"}
if($svc.State -ne "Stopped"){throw "service must begin stopped"}
if($svc.StartMode -ne "Manual"){throw "service must remain manual-start"}
if($svc.StartName -notmatch '(^|\\)ACPExecutorLab$'){throw "unexpected service account"}
$sidText=(& sc.exe qsidtype $ServiceName 2>&1)-join "`n"
if($sidText -notmatch 'SERVICE_SID_TYPE:\s+RESTRICTED'){throw "restricted service SID required"}
if((Get-FileHash -LiteralPath $ExpectedBinary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256){throw "identity probe hash mismatch"}

$src=@"
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
public static class ACPTokenInspector {
 const UInt32 TOKEN_QUERY=0x0008; const int TokenPrivileges=3;
 [StructLayout(LayoutKind.Sequential)] public struct LUID { public UInt32 LowPart; public Int32 HighPart; }
 [StructLayout(LayoutKind.Sequential)] public struct LAA { public LUID Luid; public UInt32 Attributes; }
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr h,UInt32 a,out IntPtr t);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(IntPtr t,int c,IntPtr b,UInt32 l,out UInt32 r);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool LookupPrivilegeName(string s,ref LUID l,StringBuilder n,ref int c);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool CloseHandle(IntPtr h);
 public static string[] Privileges(int pid) {
  var p=Process.GetProcessById(pid); IntPtr t;
  if(!OpenProcessToken(p.Handle,TOKEN_QUERY,out t)) throw new Win32Exception(Marshal.GetLastWin32Error());
  try { UInt32 len=0; GetTokenInformation(t,TokenPrivileges,IntPtr.Zero,0,out len); IntPtr b=Marshal.AllocHGlobal((int)len);
   try { if(!GetTokenInformation(t,TokenPrivileges,b,len,out len)) throw new Win32Exception(Marshal.GetLastWin32Error());
    int count=Marshal.ReadInt32(b); int off=4, size=Marshal.SizeOf(typeof(LAA)); var rows=new List<string>();
    for(int i=0;i<count;i++){var la=(LAA)Marshal.PtrToStructure(new IntPtr(b.ToInt64()+off+i*size),typeof(LAA));int n=0;LookupPrivilegeName(null,ref la.Luid,null,ref n);var sb=new StringBuilder(n+1);if(!LookupPrivilegeName(null,ref la.Luid,sb,ref n))throw new Win32Exception(Marshal.GetLastWin32Error());rows.Add(sb.ToString()+"|"+la.Attributes.ToString());}
    return rows.ToArray();
   } finally {Marshal.FreeHGlobal(b);}
  } finally {CloseHandle(t);}
 }
}
"@
Add-Type -TypeDefinition $src -Language CSharp

Start-Service -Name $ServiceName
try {
 $deadline=(Get-Date).AddSeconds(10)
 do{$svc=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'";if($svc.State -eq "Running"){break};Start-Sleep -Milliseconds 200}while((Get-Date)-lt $deadline)
 if($svc.State -ne "Running"){throw "service did not reach Running"}
 $pidValue=[int]$svc.ProcessId
 $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue"
 if(-not $proc){throw "service process missing"}
 $ownerSid=(Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid).Sid
 $expectedSid=(Get-LocalUser $ExpectedWorkerName).SID.Value
 if($ownerSid -ne $expectedSid){throw "service process SID mismatch"}
 $actualPath=[IO.Path]::GetFullPath($proc.ExecutablePath)
 if($actualPath -ine [IO.Path]::GetFullPath($ExpectedBinary)){throw "service process path mismatch"}
 if((Get-FileHash -LiteralPath $actualPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256){throw "service process hash mismatch"}
 $raw=[ACPTokenInspector]::Privileges($pidValue)
 $privs=@($raw|ForEach-Object{$parts=$_ -split '\|',2;[pscustomobject]@{name=$parts[0];attributes=[uint32]$parts[1]}})
 [pscustomobject]@{
  schema_version="agent-control-plane.direct-service-token-observation.v1"
  service_name=$ServiceName
  service_pid=$pidValue
  process_owner_sid=$ownerSid
  expected_worker_sid=$expectedSid
  service_sid_type="RESTRICTED"
  process_path=$actualPath
  process_sha256=$ExpectedSha256
  privilege_count=$privs.Count
  privileges=$privs
  live_service_token_privileges_observed=$true
  minimal_service_token_verified=$false
 }|ConvertTo-Json -Depth 7
} finally {
 Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
}
$final=Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if($final.State -ne "Stopped"){throw "service failed to return to Stopped"}
[pscustomobject]@{service_name=$ServiceName;final_state=$final.State;bounded_start_stop_completed=$true}|ConvertTo-Json
