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

# Presence of these files marks a complete model directory.
_WHISPER_SENTINEL = "openvino_encoder_model.xml"  # seq2seq: encoder + decoder IR
_LLM_SENTINEL = "openvino_model.xml"  # decoder-only LLM IR


def is_present(model_dir: Path, sentinel: str = _WHISPER_SENTINEL) -> bool:
    return (model_dir / sentinel).is_file()


def _snapshot(repo: str, dest: Path, logger: logging.Logger) -> None:
    from huggingface_hub import snapshot_download

    logger.info("downloading %s -> %s", repo, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=repo, local_dir=dest)


def fetch(settings: Settings, logger: logging.Logger) -> Path:
    dest = settings.model_dir
    if is_present(dest):
        logger.info("model already present: %s", dest)
        return dest

    model_id = settings.model_id

    if model_id.startswith("openai/whisper-"):
        size = model_id.removeprefix("openai/whisper-")
        repo = f"OpenVINO/whisper-{size}-fp16-ov"
        try:
            _snapshot(repo, dest, logger)
            if is_present(dest):
                return dest
            logger.warning("download of %s incomplete, falling back to export", repo)
        except Exception:
            logger.exception("pre-converted download failed, falling back to export")

    dest.parent.mkdir(parents=True, exist_ok=True)

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
        raise RuntimeError(f"export finished but {dest / _WHISPER_SENTINEL} is missing")
    return dest


def fetch_cleanup(settings: Settings, logger: logging.Logger) -> Path:
    """Fetch the LLM cleanup model. Unlike Whisper there is no export fallback:
    the configured id must already be an OpenVINO IR repo (for NPU it must be
    INT4 symmetric channel-wise, e.g. the OpenVINO org *-int4-cw-ov repos)."""
    dest = settings.cleanup_model_dir
    if is_present(dest, _LLM_SENTINEL):
        logger.info("cleanup model already present: %s", dest)
        return dest
    _snapshot(settings.cleanup_model_id, dest, logger)
    if not is_present(dest, _LLM_SENTINEL):
        raise RuntimeError(
            f"{settings.cleanup_model_id} does not look like an OpenVINO IR LLM "
            f"({_LLM_SENTINEL} missing). Use a pre-converted repo such as "
            "OpenVINO/Phi-3.5-mini-instruct-int4-cw-ov, or export one with "
            "optimum-cli (--weight-format int4 --sym --ratio 1.0 --group-size -1)."
        )
    return dest
