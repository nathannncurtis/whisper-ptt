using System.Management;

namespace WhisperPTT.Companion.Core;

public sealed record HardwareInfo(
    string CpuName,
    int RamGB,
    bool NpuPresent,
    string NpuName,
    string NpuDriverVersion)
{
    /// <summary>OpenVINO GenAI needs NPU driver >= 32.0.100.3104 for LLMs.</summary>
    public bool NpuDriverSupportsLlm =>
        Version.TryParse(NpuDriverVersion, out var v) && v >= new Version(32, 0, 100, 3104);
}

public static class HardwareProbe
{
    public static HardwareInfo Scan()
    {
        string cpu = QueryFirst("SELECT Name FROM Win32_Processor", "Name") ?? "unknown CPU";

        int ramGb = 0;
        var ramRaw = QueryFirst("SELECT TotalPhysicalMemory FROM Win32_ComputerSystem", "TotalPhysicalMemory");
        if (ulong.TryParse(ramRaw, out var bytes))
            ramGb = (int)Math.Round(bytes / (1024.0 * 1024 * 1024));

        // Intel NPUs enumerate as "Intel(R) AI Boost" in Device Manager.
        string? npuName = QueryFirst(
            "SELECT Name FROM Win32_PnPEntity WHERE Name LIKE '%AI Boost%'", "Name");
        string driver = "";
        if (npuName is not null)
            driver = QueryFirst(
                "SELECT DriverVersion FROM Win32_PnPSignedDriver WHERE DeviceName LIKE '%AI Boost%'",
                "DriverVersion") ?? "";

        return new HardwareInfo(cpu, ramGb, npuName is not null, npuName ?? "", driver);
    }

    private static string? QueryFirst(string wql, string property)
    {
        try
        {
            using var searcher = new ManagementObjectSearcher(wql);
            foreach (var obj in searcher.Get())
                return obj[property]?.ToString();
        }
        catch
        {
            // WMI hiccups shouldn't kill the wizard; caller treats null as absent.
        }
        return null;
    }
}
