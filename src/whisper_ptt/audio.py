"""Microphone capture: 16 kHz mono float32 via sounddevice."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


class Recorder:
    """Accumulates mic audio between start() and stop()."""

    def __init__(self, sample_rate: int = 16000, mic_index: int | None = None):
        self.sample_rate = sample_rate
        self.mic_index = mic_index
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("already recording")
        self._chunks = []

        def callback(indata, frames, time_info, status):
            with self._lock:
                self._chunks.append(indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.mic_index,
            callback=callback,
        )
        self._stream.start()

    def snapshot(self) -> np.ndarray:
        """Copy of everything recorded so far, without stopping the stream.
        Used by the live-transcription worker while recording continues."""
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)

    def stop(self) -> np.ndarray:
        """Stop capture and return the recorded audio as 1-D float32."""
        if self._stream is None:
            raise RuntimeError("not recording")
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def cancel(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._chunks = []
