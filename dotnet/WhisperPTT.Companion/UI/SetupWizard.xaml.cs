using System.IO;
using System.Windows;
using System.Windows.Shapes;
using WhisperPTT.Companion.Core;

namespace WhisperPTT.Companion.UI;

public partial class SetupWizard
{
    private static readonly (string Label, bool English)[] Languages =
    {
        ("English", true),
        ("Spanish", false), ("French", false), ("German", false), ("Italian", false),
        ("Portuguese", false), ("Dutch", false), ("Japanese", false), ("Chinese", false),
        ("Korean", false), ("Other / multilingual", false),
    };

    private readonly string _root;
    private int _step;
    private HardwareInfo? _hw;
    private WhisperModel? _recommended;
    private LlmModel? _llmPlan;
    private CancellationTokenSource? _cts;

    public SetupWizard(string root)
    {
        _root = root;
        InitializeComponent();
        foreach (var (label, _) in Languages)
            LanguageBox.Items.Add(label);
        LanguageBox.SelectedIndex = 0;
    }

    private bool English => Languages[Math.Max(0, LanguageBox.SelectedIndex)].English;

    private async void OnNext(object sender, RoutedEventArgs e)
    {
        switch (_step)
        {
            case 0:
                ShowStep(1);
                await ScanAsync();
                break;
            case 1:
                PrepareRecommendation();
                ShowStep(2);
                break;
            case 2:
                ShowStep(3);
                await InstallAsync();
                break;
            case 3:
                Close();
                break;
        }
    }

    private void OnBack(object sender, RoutedEventArgs e)
    {
        if (_step > 0 && _step < 3)
            ShowStep(_step - 1);
    }

    private void ShowStep(int step)
    {
        _step = step;
        StepLanguage.Visibility = step == 0 ? Visibility.Visible : Visibility.Collapsed;
        StepScan.Visibility = step == 1 ? Visibility.Visible : Visibility.Collapsed;
        StepModel.Visibility = step == 2 ? Visibility.Visible : Visibility.Collapsed;
        StepInstall.Visibility = step == 3 ? Visibility.Visible : Visibility.Collapsed;
        BackBtn.Visibility = step is 1 or 2 ? Visibility.Visible : Visibility.Collapsed;
        NextBtn.Content = step switch { 2 => "Install", 3 => "Finish", _ => "Next" };
        NextBtn.IsEnabled = step != 3; // re-enabled when install completes
    }

    private async Task ScanAsync()
    {
        _hw = await Task.Run(HardwareProbe.Scan);
        CpuText.Text = _hw.CpuName;
        RamText.Text = $"{_hw.RamGB} GB";
        NpuText.Text = _hw.NpuPresent
            ? $"{_hw.NpuName} (driver {_hw.NpuDriverVersion})"
            : "Not detected — will run on CPU (slower; consider enabling the NPU in BIOS or installing the Intel NPU driver)";
        NpuDot.SetResourceReference(Shape.FillProperty,
            _hw.NpuPresent ? "SystemFillColorSuccessBrush" : "SystemFillColorCriticalBrush");

        bool llmCapable = ModelCatalog.RecommendLlm(_hw) is not null;
        LlmCheck.IsEnabled = llmCapable;
        if (!llmCapable)
        {
            LlmCheck.IsChecked = false;
            LlmNote.Text = !_hw.NpuPresent
                ? "Unavailable: needs an NPU."
                : !_hw.NpuDriverSupportsLlm
                    ? $"Unavailable: NPU driver {_hw.NpuDriverVersion} is older than 32.0.100.3104 — update the Intel NPU driver to enable."
                    : "Unavailable: needs at least 16 GB RAM.";
        }
    }

    private void PrepareRecommendation()
    {
        bool withLlm = LlmCheck.IsChecked == true;
        _recommended = ModelCatalog.Recommend(_hw!, English, withLlm);
        _llmPlan = withLlm ? ModelCatalog.RecommendLlm(_hw!) : null;

        RecName.Text = _recommended.Id;
        RecMeta.Text = $"{_recommended.SizeGB:0.0} GB download — {_recommended.Blurb}";

        ModelBox.Items.Clear();
        foreach (var m in ModelCatalog.Whisper.Where(m => !m.EnglishOnly || English))
            ModelBox.Items.Add($"{m.Id}  ({m.SizeGB:0.0} GB)");
        ModelBox.SelectedIndex = ModelCatalog.Whisper
            .Where(m => !m.EnglishOnly || English).ToList()
            .FindIndex(m => m.Id == _recommended.Id);

        LlmPlanText.Text = _llmPlan is null
            ? "LLM cleanup: off."
            : $"LLM cleanup: {_llmPlan.Id} ({_llmPlan.SizeGB:0.0} GB) will also be downloaded ({_llmPlan.Blurb}).";
    }

    private async Task InstallAsync()
    {
        var candidates = ModelCatalog.Whisper.Where(m => !m.EnglishOnly || English).ToList();
        var chosen = ModelBox.SelectedIndex >= 0 ? candidates[ModelBox.SelectedIndex] : _recommended!;

        var ini = new IniFile(AppPaths.ConfigPath(_root));
        var modelsDir = AppPaths.ModelsDir(_root, ini);
        _cts = new CancellationTokenSource();
        var dl = new HfDownloader();
        var progress = new Progress<HfDownloader.Progress>(p =>
        {
            InstallStatus.Text = $"{p.FileName}  ({p.FileIndex}/{p.FileCount})";
            InstallBar.Value = p.BytesTotal > 0 ? 100.0 * p.BytesDone / p.BytesTotal : 0;
        });

        try
        {
            await dl.DownloadRepoAsync(chosen.Repo,
                System.IO.Path.Combine(modelsDir, ModelCatalog.DirNameFor(chosen.Id)), progress, _cts.Token);
            if (_llmPlan is not null)
                await dl.DownloadRepoAsync(_llmPlan.Repo,
                    System.IO.Path.Combine(modelsDir, ModelCatalog.DirNameFor(_llmPlan.Id)), progress, _cts.Token);

            ini.Set("model", "id", chosen.Id);
            ini.Set("cleanup", "enabled", _llmPlan is null ? "false" : "true");
            if (_llmPlan is not null)
                ini.Set("cleanup", "id", _llmPlan.Id);
            ini.Save();

            InstallStatus.Text = "Done.";
            InstallBar.Value = 100;
            DoneBar.IsOpen = true;
        }
        catch (Exception ex)
        {
            InstallStatus.Text = $"Download failed: {ex.Message}";
        }
        NextBtn.IsEnabled = true;
    }

    protected override void OnClosed(EventArgs e)
    {
        _cts?.Cancel();
        base.OnClosed(e);
    }
}
