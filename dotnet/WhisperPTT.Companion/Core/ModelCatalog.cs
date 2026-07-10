namespace WhisperPTT.Companion.Core;

public sealed record WhisperModel(
    string Id,          // config.ini model.id value
    string Repo,        // pre-converted HF repo to download
    double SizeGB,
    bool EnglishOnly,
    string Blurb);

public sealed record LlmModel(
    string Id,
    string Repo,
    double SizeGB,
    string Blurb);

public static class ModelCatalog
{
    // Ordered smallest -> largest. Sizes are on-disk fp16 IR.
    public static readonly WhisperModel[] Whisper =
    {
        new("openai/whisper-base",            "OpenVINO/whisper-base-fp16-ov",            0.15, false, "Fastest; fine for quick notes"),
        new("openai/whisper-base.en",         "OpenVINO/whisper-base.en-fp16-ov",         0.15, true,  "Fastest; fine for quick notes"),
        new("openai/whisper-small",           "OpenVINO/whisper-small-fp16-ov",           0.50, false, "Good balance of speed and accuracy"),
        new("openai/whisper-small.en",        "OpenVINO/whisper-small.en-fp16-ov",        0.50, true,  "Good balance of speed and accuracy"),
        new("openai/whisper-medium",          "OpenVINO/whisper-medium-fp16-ov",          1.50, false, "High accuracy; heavier compute"),
        new("openai/whisper-medium.en",       "OpenVINO/whisper-medium.en-fp16-ov",       1.50, true,  "High accuracy; heavier compute"),
        new("distil-whisper/distil-large-v3", "OpenVINO/distil-whisper-large-v3-fp16-ov", 1.40, true,  "Best accuracy (large-v3 distilled); background transcription lags slightly on long dictations"),
    };

    // NPU-compatible (INT4 symmetric channel-wise) instruct models.
    public static readonly LlmModel[] Llms =
    {
        new("OpenVINO/Phi-3.5-mini-instruct-int4-cw-ov", "OpenVINO/Phi-3.5-mini-instruct-int4-cw-ov", 2.0,
            "3.8B; weak instruction-following for cleanup in our testing"),
        new("OpenVINO/gemma-3-4b-it-int4-cw-ov", "OpenVINO/gemma-3-4b-it-int4-cw-ov", 2.4,
            "4B; untested for cleanup on this pipeline"),
    };

    public static string DirNameFor(string modelId) => modelId.Replace("/", "__");

    /// <summary>
    /// Pick the best Whisper model for the hardware. If an LLM will share the
    /// NPU and RAM, step down one rung so dictation latency stays snappy.
    /// </summary>
    public static WhisperModel Recommend(HardwareInfo hw, bool english, bool withLlm)
    {
        string size;
        if (!hw.NpuPresent)
            size = "base";              // CPU fallback: keep it light
        else if (hw.RamGB >= 16 && !withLlm)
            size = english ? "distil" : "medium";
        else if (hw.RamGB >= 8)
            size = "small";
        else
            size = "base";

        if (size == "distil")
            return Whisper.First(m => m.Id.StartsWith("distil"));
        var id = $"openai/whisper-{size}" + (english ? ".en" : "");
        return Whisper.First(m => m.Id == id);
    }

    public static LlmModel? RecommendLlm(HardwareInfo hw)
    {
        if (!hw.NpuPresent || !hw.NpuDriverSupportsLlm || hw.RamGB < 16)
            return null;
        return Llms[0];
    }
}
