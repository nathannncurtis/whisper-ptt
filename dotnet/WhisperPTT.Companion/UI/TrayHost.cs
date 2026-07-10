using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Windows;
using WhisperPTT.Companion.Core;
using WinForms = System.Windows.Forms;

namespace WhisperPTT.Companion.UI;

/// <summary>
/// Tray icon + menu: backend status, settings window, setup wizard, restart.
/// The icon is drawn in code (waveform pill motif) so the repo carries no
/// binary assets.
/// </summary>
public sealed class TrayHost : IDisposable
{
    private readonly string _root;
    private readonly WinForms.NotifyIcon _icon;

    public TrayHost(string root)
    {
        _root = root;
        _icon = new WinForms.NotifyIcon
        {
            Icon = DrawIcon(),
            Text = "WhisperPTT",
            Visible = true,
            ContextMenuStrip = BuildMenu(),
        };
        _icon.DoubleClick += (_, _) => OpenSettings();
    }

    private WinForms.ContextMenuStrip BuildMenu()
    {
        var menu = new WinForms.ContextMenuStrip();
        menu.Items.Add("Backend status", null, async (_, _) => await ShowStatusAsync());
        menu.Items.Add("Settings…", null, (_, _) => OpenSettings());
        menu.Items.Add("Setup wizard…", null, (_, _) => OpenWizard());
        menu.Items.Add(new WinForms.ToolStripSeparator());
        menu.Items.Add("Open backend log", null, (_, _) => OpenLog());
        menu.Items.Add("Restart backend", null, async (_, _) => await RestartBackendAsync());
        menu.Items.Add(new WinForms.ToolStripSeparator());
        menu.Items.Add("Exit companion", null, (_, _) => System.Windows.Application.Current.Shutdown());
        return menu;
    }

    private async Task ShowStatusAsync()
    {
        var device = await BackendLifecycle.ClientFor(_root).PingAsync();
        _icon.ShowBalloonTip(4000, "WhisperPTT",
            device switch
            {
                null => "Backend is not running.",
                "loading" => "Backend is loading the model…",
                _ => $"Ready — active device: {device}",
            },
            WinForms.ToolTipIcon.None);
    }

    private void OpenSettings()
    {
        foreach (Window w in System.Windows.Application.Current.Windows)
            if (w is SettingsWindow existing) { existing.Activate(); return; }
        new SettingsWindow(_root).Show();
    }

    private void OpenWizard()
    {
        foreach (Window w in System.Windows.Application.Current.Windows)
            if (w is SetupWizard existing) { existing.Activate(); return; }
        new SetupWizard(_root).Show();
    }

    private void OpenLog()
    {
        var ini = new IniFile(AppPaths.ConfigPath(_root));
        var log = AppPaths.LogPath(_root, ini);
        if (File.Exists(log))
            Process.Start(new ProcessStartInfo("notepad.exe", $"\"{log}\""));
    }

    private Task RestartBackendAsync() => BackendLifecycle.RestartAsync(_root);

    /// <summary>16..48px tray icon: dark rounded pill, mauve accent bars.</summary>
    private static Icon DrawIcon()
    {
        using var bmp = new Bitmap(32, 32);
        using var g = Graphics.FromImage(bmp);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        using (var bg = new SolidBrush(System.Drawing.Color.FromArgb(255, 32, 32, 32)))
            g.FillEllipse(bg, 0, 0, 32, 32);
        using var bar = new SolidBrush(System.Drawing.Color.FromArgb(255, 0xB0, 0xA8, 0xB9));
        int[] heights = { 8, 16, 22, 14, 9 };
        for (int i = 0; i < heights.Length; i++)
        {
            int h = heights[i];
            var rect = new RectangleF(5 + i * 5, 16 - h / 2f, 3.2f, h);
            using var path = Capsule(rect);
            g.FillPath(bar, path);
        }
        return Icon.FromHandle(bmp.GetHicon());
    }

    private static GraphicsPath Capsule(RectangleF r)
    {
        var path = new GraphicsPath();
        float d = r.Width;
        path.AddArc(r.X, r.Y, d, d, 180, 180);
        path.AddArc(r.X, r.Bottom - d, d, d, 0, 180);
        path.CloseFigure();
        return path;
    }

    public void Dispose()
    {
        _icon.Visible = false;
        _icon.Dispose();
    }
}
