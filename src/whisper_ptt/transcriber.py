"""OpenVINO GenAI Whisper pipeline with device fallback.

Policy: try devices in configured order (default NPU, CPU, GPU). A device only
counts as working after BOTH pipeline creation and a warmup inference succeed,
because NPU failures can surface on first generate() rather than at load time.
The real exception is logged before falling back.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import openvino_genai


class Transcriber:
    def __init__(
        self,
        model_dir: Path,
        device_order: tuple[str, ...],
        logger: logging.Logger,
    ):
        self.logger = logger
        last_error: Exception | None = None
        for device in device_order:
            try:
                t0 = time.perf_counter()
                pipeline = openvino_genai.WhisperPipeline(str(model_dir), device=device)
                # Warmup on 0.5 s of silence: validates the device end-to-end and
                # front-loads compilation cost so the first utterance isn't slow.
                pipeline.generate(np.zeros(8000, dtype=np.float32))
                elapsed = time.perf_counter() - t0
                self.pipeline = pipeline
                self.device = device
                logger.info(
                    "pipeline ready on %s (load+warmup %.1fs, model=%s)",
                    device, elapsed, model_dir.name,
                )
                return
            except Exception as exc:
                last_error = exc
                logger.exception("device %s failed, trying next in order", device)
        raise RuntimeError(
            f"no device in {device_order} could run the model"
        ) from last_error

    def transcribe(self, audio: np.ndarray) -> str:
        """Raw transcription of 16 kHz mono float32 audio; no post-processing."""
        result = self.pipeline.generate(audio)
        return "".join(result.texts)
