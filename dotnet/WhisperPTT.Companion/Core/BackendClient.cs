using System.Net.Http;

namespace WhisperPTT.Companion.Core;

/// <summary>Thin client for the Python backend's localhost HTTP protocol.</summary>
public sealed class BackendClient(string host, int port)
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(3) };
    private readonly string _base = $"http://{host}:{port}";

    /// <summary>Returns the active device string when ready, "loading", or null (unreachable).</summary>
    public async Task<string?> PingAsync()
    {
        try
        {
            using var resp = await Http.GetAsync($"{_base}/ping");
            var body = await resp.Content.ReadAsStringAsync();
            return resp.IsSuccessStatusCode ? body : "loading";
        }
        catch
        {
            return null;
        }
    }

    public async Task<bool> ShutdownAsync()
    {
        try
        {
            using var resp = await Http.PostAsync($"{_base}/shutdown", null);
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }
}
