"""Load settings from config.ini (shared with the AHK front-end)."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path  # directory containing config.ini; all relative paths resolve against it
    model_id: str
    models_dir: Path
    device_order: tuple[str, ...]
    mic_index: int | None  # None = system default
    sample_rate: int
    silence_rms: float
    pause_media: bool
    host: str
    port: int
    log_level: str
    log_dir: Path
    cleanup_enabled: bool
    cleanup_model_id: str
    cleanup_device_order: tuple[str, ...]
    cleanup_max_new_tokens: int

    @property
    def model_dir(self) -> Path:
        """models/openai__whisper-base style directory for the configured model."""
        return self.models_dir / self.model_id.replace("/", "__")

    @property
    def cleanup_model_dir(self) -> Path:
        return self.models_dir / self.cleanup_model_id.replace("/", "__")


def load(config_path: str | Path = "config.ini") -> Settings:
    path = Path(config_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    root = path.parent

    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cp.read(path, encoding="utf-8")

    mic_raw = cp.get("audio", "mic_index", fallback="default").strip().lower()
    mic_index = None if mic_raw in ("", "default") else int(mic_raw)

    def parse_order(section: str, fallback: str) -> tuple[str, ...]:
        return tuple(
            d.strip().upper()
            for d in cp.get(section, "order", fallback=fallback).split(",")
            if d.strip()
        )

    return Settings(
        root=root,
        model_id=cp.get("model", "id", fallback="openai/whisper-base").strip(),
        models_dir=root / cp.get("model", "dir", fallback="models").strip(),
        device_order=parse_order("devices", "NPU, CPU"),
        mic_index=mic_index,
        sample_rate=cp.getint("audio", "sample_rate", fallback=16000),
        silence_rms=cp.getfloat("audio", "silence_rms", fallback=0.002),
        pause_media=cp.getboolean("media", "pause_on_record", fallback=True),
        host=cp.get("server", "host", fallback="127.0.0.1").strip(),
        port=cp.getint("server", "port", fallback=8765),
        log_level=cp.get("logging", "level", fallback="INFO").strip().upper(),
        log_dir=root / cp.get("logging", "dir", fallback="logs").strip(),
        cleanup_enabled=cp.getboolean("cleanup", "enabled", fallback=False),
        cleanup_model_id=cp.get(
            "cleanup", "id", fallback="OpenVINO/Phi-3.5-mini-instruct-int4-cw-ov"
        ).strip(),
        cleanup_device_order=parse_order("cleanup", "NPU, CPU"),
        cleanup_max_new_tokens=cp.getint("cleanup", "max_new_tokens", fallback=256),
    )
