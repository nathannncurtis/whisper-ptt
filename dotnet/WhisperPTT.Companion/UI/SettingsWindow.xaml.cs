using System.Windows;
using WhisperPTT.Companion.Core;

namespace WhisperPTT.Companion.UI;

public partial class SettingsWindow
{
    private readonly string _root;
    private readonly IniFile _ini;

    public SettingsWindow(string root)
    {
        _root = root;
        _ini = new IniFile(AppPaths.ConfigPath(root));
        InitializeComponent();
        Load();
    }

    private void Load()
    {
        HotkeyBox.Text = _ini.Get("hotkey", "key", "RCtrl");
        foreach (var m in ModelCatalog.Whisper)
            ModelBox.Items.Add(m.Id);
        ModelBox.Text = _ini.Get("model", "id", "openai/whisper-base");
        MicBox.Text = _ini.Get("audio", "mic_index", "default");
        GateBox.Text = _ini.Get("audio", "silence_rms", "0.003");
        PauseMediaCheck.IsChecked = _ini.Get("media", "pause_on_record", "true")
            .Equals("true", StringComparison.OrdinalIgnoreCase);
        CleanupCheck.IsChecked = _ini.Get("cleanup", "enabled", "false")
            .Equals("true", StringComparison.OrdinalIgnoreCase);
        CleanupModelBox.Text = _ini.Get("cleanup", "id", "");
        MinWordsBox.Text = _ini.Get("cleanup", "min_words", "5");
    }

    private void OnSave(object sender, RoutedEventArgs e)
    {
        _ini.Reload(); // don't clobber concurrent edits with a stale copy
        _ini.Set("hotkey", "key", HotkeyBox.Text.Trim());
        _ini.Set("model", "id", ModelBox.Text.Trim());
        _ini.Set("audio", "mic_index", MicBox.Text.Trim());
        _ini.Set("audio", "silence_rms", GateBox.Text.Trim());
        _ini.Set("media", "pause_on_record", PauseMediaCheck.IsChecked == true ? "true" : "false");
        _ini.Set("cleanup", "enabled", CleanupCheck.IsChecked == true ? "true" : "false");
        if (CleanupModelBox.Text.Trim().Length > 0)
            _ini.Set("cleanup", "id", CleanupModelBox.Text.Trim());
        _ini.Set("cleanup", "min_words", MinWordsBox.Text.Trim());
        _ini.Save();
        SavedBar.IsOpen = true;
    }

    private void OnCancel(object sender, RoutedEventArgs e) => Close();

    private async void OnRestartBackend(object sender, RoutedEventArgs e)
    {
        await BackendLifecycle.RestartAsync(_root);
        SavedBar.Title = "Backend restarting";
        SavedBar.Message = "It will be back in a few seconds (first start of a new model takes longer).";
        SavedBar.IsOpen = true;
    }
}
