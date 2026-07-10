using System.IO;

namespace WhisperPTT.Companion.Core;

/// <summary>
/// Minimal INI reader/writer that PRESERVES comments and formatting.
/// config.ini is heavily commented documentation — a naive rewrite would
/// destroy it, so writes are targeted line edits.
/// </summary>
public sealed class IniFile
{
    public string Path { get; }
    private List<string> _lines;

    public IniFile(string path)
    {
        Path = path;
        _lines = File.Exists(path) ? File.ReadAllLines(path).ToList() : new List<string>();
    }

    public void Reload() => _lines = File.ReadAllLines(Path).ToList();

    public string Get(string section, string key, string fallback = "")
    {
        bool inSection = false;
        foreach (var raw in _lines)
        {
            var line = raw.Trim();
            if (line.StartsWith('[') && line.EndsWith(']'))
            {
                inSection = line[1..^1].Equals(section, StringComparison.OrdinalIgnoreCase);
                continue;
            }
            if (!inSection || line.StartsWith(';') || line.StartsWith('#'))
                continue;
            int eq = line.IndexOf('=');
            if (eq < 0)
                continue;
            if (line[..eq].Trim().Equals(key, StringComparison.OrdinalIgnoreCase))
            {
                var value = line[(eq + 1)..];
                int comment = value.IndexOfAny(new[] { ';', '#' });
                if (comment >= 0)
                    value = value[..comment];
                return value.Trim();
            }
        }
        return fallback;
    }

    /// <summary>Replace a key's value in place; append to the section if missing.</summary>
    public void Set(string section, string key, string value)
    {
        bool inSection = false;
        int sectionEnd = -1; // last content line of the target section
        for (int i = 0; i < _lines.Count; i++)
        {
            var line = _lines[i].Trim();
            if (line.StartsWith('[') && line.EndsWith(']'))
            {
                if (inSection)
                    break;
                inSection = line[1..^1].Equals(section, StringComparison.OrdinalIgnoreCase);
                if (inSection)
                    sectionEnd = i;
                continue;
            }
            if (!inSection)
                continue;
            if (line.Length > 0)
                sectionEnd = i;
            if (line.StartsWith(';') || line.StartsWith('#'))
                continue;
            int eq = line.IndexOf('=');
            if (eq >= 0 && line[..eq].Trim().Equals(key, StringComparison.OrdinalIgnoreCase))
            {
                _lines[i] = $"{key} = {value}";
                return;
            }
        }
        if (sectionEnd >= 0)
            _lines.Insert(sectionEnd + 1, $"{key} = {value}");
        else
        {
            _lines.Add("");
            _lines.Add($"[{section}]");
            _lines.Add($"{key} = {value}");
        }
    }

    public void Save() => File.WriteAllLines(Path, _lines);
}
