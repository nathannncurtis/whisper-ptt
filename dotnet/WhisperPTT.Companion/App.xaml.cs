using System.Windows;
using System.Windows.Media;
using WhisperPTT.Companion.Core;
using WhisperPTT.Companion.UI;
using Wpf.Ui.Appearance;
using Wpf.Ui.Controls;

namespace WhisperPTT.Companion;

public partial class App : System.Windows.Application
{
    private TrayHost? _tray;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // Wincopy design language: dark theme, Mica, muted mauve accent.
        var accent = System.Windows.Media.Color.FromArgb(0xFF, 0xB0, 0xA8, 0xB9);
        ApplicationAccentColorManager.Apply(accent, ApplicationTheme.Dark, false);
        ApplicationThemeManager.Apply(ApplicationTheme.Dark, WindowBackdropType.Mica, false);

        var root = AppPaths.FindRoot();
        if (root is null)
        {
            System.Windows.MessageBox.Show(
                "config.ini not found near the executable — run from the WhisperPTT folder.",
                "WhisperPTT", System.Windows.MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
            return;
        }

        if (e.Args.Contains("--setup"))
        {
            var wizard = new SetupWizard(root);
            wizard.Closed += (_, _) => Shutdown();
            wizard.Show();
        }
        else
        {
            _tray = new TrayHost(root);
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        base.OnExit(e);
    }
}
