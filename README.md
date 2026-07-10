# WhisperPTT

Fully local push-to-talk dictation for Windows. Hold a key, speak, release —
the transcription is typed into whatever window has focus. Whisper inference
runs on the Intel NPU via OpenVINO (CPU fallback; GPU only as a last resort).
No cloud, no telemetry.

## Architecture

Two processes:

```
ahk\WhisperPTT.ahk (AutoHotkey v2)          src\whisper_ptt (Python, headless)
┌─────────────────────────────┐   HTTP     ┌──────────────────────────────────┐
│ global hold-to-talk hotkey  │ localhost  │ mic capture (sounddevice, 16 kHz)│
│ recording indicator overlay ├───────────►│ Whisper via openvino_genai       │
│ SendText into focused win   │◄───────────┤ NPU → CPU → GPU device fallback  │
│ starts/stops the backend    │ plain text │ rotating logs w/ latency stats   │
└─────────────────────────────┘            └──────────────────────────────────┘
```

Protocol: localhost HTTP with **plain UTF-8 text bodies** — even simpler than
NDJSON, and the AHK side needs zero parsing (`WinHttp.WinHttpRequest` COM +
status codes). Endpoints: `POST /start`, `POST /stop` (returns the text),
`POST /cancel`, `POST /shutdown`, `GET /ping` (returns the active device,
`503` while the model loads).

Post-processing is an ordered pipeline in `src/whisper_ptt/postprocess.py`
(currently trim + capitalize); an LLM cleanup pass can be appended later
without touching anything else.

## Setup (dev machine)

Requires CPython 3.10–3.12 x64 and AutoHotkey v2.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -e .

# 1. Probe FIRST — confirms the NPU enumerates before going further
.venv\Scripts\python scripts\probe_devices.py

# 2. Fetch the model (skipped automatically if models\ already has it)
.venv\Scripts\python -m whisper_ptt --fetch-model

# 3. Run the front-end (it launches the backend itself)
"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe" ahk\WhisperPTT.ahk
```

`scripts\download_model.ps1` is a Python-free bootstrap that downloads the
pre-converted IR (`OpenVINO/whisper-base-fp16-ov`) over plain HTTP.

## Configuration — `config.ini`

| Section.key      | Default              | Notes                                    |
|------------------|----------------------|------------------------------------------|
| hotkey.key       | `RCtrl`              | any AHK v2 key name                       |
| model.id         | `openai/whisper-base`| swap to `-small`/`-medium`, re-fetch      |
| devices.order    | `NPU, CPU, GPU`      | first device that loads+warms up wins     |
| audio.mic_index  | `default`            | list with `python -m sounddevice`         |
| server.port      | `8765`               |                                           |
| logging.level    | `INFO`               | logs rotate in `logs\backend.log`         |

Device policy: a device counts as working only after pipeline creation **and**
a warmup inference succeed (NPU failures often surface on first generate).
Real exceptions are logged before falling back. The active device is printed
at startup, logged, and shown in the tray "Backend status".

Every utterance logs `audio=…s proc=…s rtf=…` for latency tracking.

## CI/CD

- `ci.yml` — push/PR: install, byte-compile, import + config smoke test.
- `release.yml` — on `v*` tags: PyInstaller-bundles the backend, compiles the
  AHK script with Ahk2Exe, wraps both in a **per-user** Inno Setup installer
  (`%LOCALAPPDATA%\Programs\WhisperPTT`, no admin needed), uploads it to a
  GitHub release. The installed app downloads the model on first run.

Release: `git tag v0.1.0 && git push --tags`.

## Repo layout

```
ahk/            AutoHotkey v2 front-end
src/whisper_ptt Python backend package
scripts/        NPU probe + Python-free model bootstrap
installer/      Inno Setup script + PyInstaller entry point
.github/        CI + release workflows
models/, logs/  runtime, gitignored
```
