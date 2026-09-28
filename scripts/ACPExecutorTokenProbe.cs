using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.ServiceProcess;
using System.Text;

public sealed class ACPExecutorTokenProbe : ServiceBase {
    const string EvidencePath = @"C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\token-evidence.json";
    public ACPExecutorTokenProbe() {
        ServiceName = "ACPExecutorLabProbe";
        CanStop = true;
        AutoLog = false;
    }
    protected override void OnStart(string[] args) {
        try { File.WriteAllText(EvidencePath, TokenEvidence.Capture(), new UTF8Encoding(false)); }
        catch { Stop(); }
    }
    protected override void OnStop() { }
    public static void Main() { ServiceBase.Run(new ACPExecutorTokenProbe()); }
}

static class TokenEvidence {
    const UInt32 TOKEN_QUERY = 0x0008;
    const int TokenPrivileges = 3;
    [StructLayout(LayoutKind.Sequential)] struct LUID { public UInt32 LowPart; public Int32 HighPart; }
    [StructLayout(LayoutKind.Sequential)] struct LUID_AND_ATTRIBUTES { public LUID Luid; public UInt32 Attributes; }
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr ProcessHandle, UInt32 DesiredAccess, out IntPtr TokenHandle);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr TokenHandle, int TokenInformationClass, IntPtr TokenInformation, UInt32 TokenInformationLength, out UInt32 ReturnLength);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool LookupPrivilegeName(string lpSystemName, ref LUID lpLuid, StringBuilder lpName, ref int cchName);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr hObject);

    public static string Capture() {
        IntPtr token;
        if(!OpenProcessToken(Process.GetCurrentProcess().Handle, TOKEN_QUERY, out token)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            UInt32 len=0; GetTokenInformation(token, TokenPrivileges, IntPtr.Zero, 0, out len);
            IntPtr buf=Marshal.AllocHGlobal((int)len);
            try {
                if(!GetTokenInformation(token, TokenPrivileges, buf, len, out len)) throw new Win32Exception(Marshal.GetLastWin32Error());
                UInt32 count=(UInt32)Marshal.ReadInt32(buf);
                int offset=4, size=Marshal.SizeOf(typeof(LUID_AND_ATTRIBUTES));
                var rows=new List<string>();
                for(int i=0;i<count;i++) {
                    var la=(LUID_AND_ATTRIBUTES)Marshal.PtrToStructure(new IntPtr(buf.ToInt64()+offset+i*size), typeof(LUID_AND_ATTRIBUTES));
                    int n=0; LookupPrivilegeName(null, ref la.Luid, null, ref n);
                    var sb=new StringBuilder(n+1);
                    if(!LookupPrivilegeName(null, ref la.Luid, sb, ref n)) throw new Win32Exception(Marshal.GetLastWin32Error());
                    rows.Add("{\"name\":\""+Escape(sb.ToString())+"\",\"attributes\":"+la.Attributes.ToString()+"}");
                }
                return "{\"schema_version\":\"agent-control-plane.self-token-evidence.v1\",\"pid\":"+Process.GetCurrentProcess().Id+",\"privileges\":["+String.Join(",", rows.ToArray())+"]}";
            } finally { Marshal.FreeHGlobal(buf); }
        } finally { CloseHandle(token); }
    }
    static string Escape(string s){ return s.Replace("\\","\\\\").Replace("\"","\\\""); }
}
