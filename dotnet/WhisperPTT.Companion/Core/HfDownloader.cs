using System.IO;
using System.Net.Http;
using System.Text.Json;

namespace WhisperPTT.Companion.Core;

/// <summary>
/// Downloads a HuggingFace repo's files over plain HTTPS (same approach as
/// scripts/download_model.ps1). Resume-safe: .part temp files, skip existing.
/// </summary>
public sealed class HfDownloader
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromMinutes(30) };

    public sealed record Progress(string FileName, long BytesDone, long BytesTotal, int FileIndex, int FileCount);

    public async Task DownloadRepoAsync(
        string repo, string destDir, IProgress<Progress>? progress, CancellationToken ct)
    {
        Directory.CreateDirectory(destDir);

        using var listResp = await Http.GetAsync($"https://huggingface.co/api/models/{repo}", ct);
        listResp.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await listResp.Content.ReadAsStringAsync(ct));
        var files = doc.RootElement.GetProperty("siblings")
            .EnumerateArray()
            .Select(s => s.GetProperty("rfilename").GetString()!)
            .Where(f => f != ".gitattributes")
            .ToList();

        for (int i = 0; i < files.Count; i++)
        {
            var file = files[i];
            var outPath = Path.Combine(destDir, file);
            if (File.Exists(outPath))
                continue;
            Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);

            var url = $"https://huggingface.co/{repo}/resolve/main/{Uri.EscapeDataString(file)}";
            using var resp = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct);
            resp.EnsureSuccessStatusCode();
            long total = resp.Content.Headers.ContentLength ?? -1;

            var partPath = outPath + ".part";
            await using (var src = await resp.Content.ReadAsStreamAsync(ct))
            await using (var dst = File.Create(partPath))
            {
                var buffer = new byte[1 << 16];
                long done = 0;
                int read;
                while ((read = await src.ReadAsync(buffer, ct)) > 0)
                {
                    await dst.WriteAsync(buffer.AsMemory(0, read), ct);
                    done += read;
                    progress?.Report(new Progress(file, done, total, i + 1, files.Count));
                }
            }
            File.Move(partPath, outPath);
        }
    }
}
