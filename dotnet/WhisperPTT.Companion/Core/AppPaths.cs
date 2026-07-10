using System.IO;

namespace WhisperPTT.Companion.Core;

/// <summary>
/// The WhisperPTT root is wherever config.ini lives: the install dir in the
/// packaged layout, the repo root in dev (exe under dotnet\...\bin\...).
/// </summary>
public static class AppPaths
{
    public static string? FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 7 && dir is not null; i++, dir = dir.Parent)
        {
            if (File.Exists(Path.Combine(dir.FullName, "config.ini")))
                return dir.FullName;
        }
        return null;
    }

    public static string ConfigPath(string root) => Path.Combine(root, "config.ini");
    public static string ModelsDir(string root, IniFile ini) =>
        Path.Combine(root, ini.Get("model", "dir", "models"));
    public static string LogPath(string root, IniFile ini) =>
        Path.Combine(root, ini.Get("logging", "dir", "logs"), "backend.log");
}
