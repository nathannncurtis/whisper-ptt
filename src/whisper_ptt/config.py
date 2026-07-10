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
    host: str
    port: int
    log_level: str
    log_dir: Path

    @property
    def model_dir(self) -> Path:
        """models/openai__whisper-base style directory for the configured model."""
        return self.models_dir / self.model_id.replace("/", "__")


def load(config_path: str | Path = "config.ini") -> Settings:
    path = Path(config_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    root = path.parent

    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cp.read(path, encoding="utf-8")

    mic_raw = cp.get("audio", "mic_index", fallback="default").strip().lower()
    mic_index = None if mic_raw in ("", "default") else int(mic_raw)

    device_order = tuple(
        d.strip().upper()
        for d in cp.get("devices", "order", fallback="NPU, CPU").split(",")
        if d.strip()
    )

    return Settings(
        root=root,
        model_id=cp.get("model", "id", fallback="openai/whisper-base").strip(),
        models_dir=root / cp.get("model", "dir", fallback="models").strip(),
        device_order=device_order,
        mic_index=mic_index,
        sample_rate=cp.getint("audio", "sample_rate", fallback=16000),
        host=cp.get("server", "host", fallback="127.0.0.1").strip(),
        port=cp.getint("server", "port", fallback=8765),
        log_level=cp.get("logging", "level", fallback="INFO").strip().upper(),
        log_dir=root / cp.get("logging", "dir", fallback="logs").strip(),
    )
