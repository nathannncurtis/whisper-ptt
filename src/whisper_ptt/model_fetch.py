"""Fetch the configured Whisper model as OpenVINO IR.

Fast path: the OpenVINO HuggingFace org publishes pre-converted fp16 IR for the
stock Whisper sizes (base/small/medium/...), so for `openai/whisper-<size>` we
just download `OpenVINO/whisper-<size>-fp16-ov` — no torch required.

Fallback: export with optimum-cli (requires `pip install -r requirements-convert.txt`).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import Settings

# Presence of this file marks a complete model directory.
_SENTINEL = "openvino_encoder_model.xml"


def is_present(model_dir: Path) -> bool:
    return (model_dir / _SENTINEL).is_file()


def fetch(settings: Settings, logger: logging.Logger) -> Path:
    dest = settings.model_dir
    if is_present(dest):
        logger.info("model already present: %s", dest)
        return dest

    model_id = settings.model_id
    dest.parent.mkdir(parents=True, exist_ok=True)

    if model_id.startswith("openai/whisper-"):
        size = model_id.removeprefix("openai/whisper-")
        repo = f"OpenVINO/whisper-{size}-fp16-ov"
        logger.info("downloading pre-converted IR %s -> %s", repo, dest)
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=repo, local_dir=dest)
            if is_present(dest):
                return dest
            logger.warning("download of %s incomplete, falling back to export", repo)
        except Exception:
            logger.exception("pre-converted download failed, falling back to export")

    logger.info("exporting %s with optimum-cli (this needs requirements-convert.txt)", model_id)
    cmd = [
        "optimum-cli", "export", "openvino",
        "--model", model_id,
        "--weight-format", "fp16",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise RuntimeError(
            "optimum-cli not found. Install conversion deps first:\n"
            "  .venv\\Scripts\\pip install -r requirements-convert.txt"
        ) from None
    if not is_present(dest):
        raise RuntimeError(f"export finished but {dest / _SENTINEL} is missing")
    return dest
