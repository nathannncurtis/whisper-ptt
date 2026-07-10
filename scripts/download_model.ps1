# Downloads a pre-converted OpenVINO Whisper IR from HuggingFace over plain HTTP.
# Used as a bootstrap when no Python environment is available yet; the backend's
# normal path is `python -m whisper_ptt --fetch-model` (see src/whisper_ptt/model_fetch.py).
#
# Usage: powershell -File scripts\download_model.ps1 [-Repo OpenVINO/whisper-base-fp16-ov] [-Dest models\openai__whisper-base]
param(
    [string]$Repo = 'OpenVINO/whisper-base-fp16-ov',
    [string]$Dest = ''
)
$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
if (-not $Dest) { $Dest = Join-Path $root 'models\openai__whisper-base' }

New-Item -ItemType Directory -Force $Dest | Out-Null

$files = (Invoke-RestMethod "https://huggingface.co/api/models/$Repo").siblings |
    ForEach-Object { $_.rfilename } |
    Where-Object { $_ -ne '.gitattributes' }

foreach ($f in $files) {
    $out = Join-Path $Dest $f
    if (Test-Path $out) {
        Write-Host "exists, skipping: $f"
        continue
    }
    Write-Host "downloading: $f"
    # Download to a .part file first so an interrupted run never leaves a
    # truncated file that the skip-if-exists check would treat as complete.
    curl.exe -sSL --fail --retry 3 -o "$out.part" "https://huggingface.co/$Repo/resolve/main/$f"
    if ($LASTEXITCODE -ne 0) { throw "download failed: $f" }
    Move-Item "$out.part" $out
}
Write-Host "model ready in $Dest"
