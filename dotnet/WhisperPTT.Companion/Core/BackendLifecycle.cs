using System.Diagnostics;
using System.IO;

namespace WhisperPTT.Companion.Core;

public static class BackendLifecycle
{
    public static BackendClient ClientFor(string root)
    {
        var ini = new IniFile(AppPaths.ConfigPath(root));
        return new BackendClient(
            ini.Get("server", "host", "127.0.0.1"),
            int.TryParse(ini.Get("server", "port", "8765"), out var p) ? p : 8765);
    }

    /// <summary>Gracefully stop the backend, then relaunch the AHK front-end
    /// (which owns starting the Python backend and will reload config.ini).</summary>
    public static async Task RestartAsync(string root)
    {
        await ClientFor(root).ShutdownAsync();
        await Task.Delay(1500);
        string exe = Path.Combine(root, "WhisperPTT.exe");
        string ahk = Path.Combine(root, "ahk", "WhisperPTT.ahk");
        string interpreter = @"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe";
        if (File.Exists(exe))
            Process.Start(new ProcessStartInfo(exe) { WorkingDirectory = root });
        else if (File.Exists(ahk) && File.Exists(interpreter))
            Process.Start(new ProcessStartInfo(interpreter, $"\"{ahk}\"") { WorkingDirectory = root });
    }
}
