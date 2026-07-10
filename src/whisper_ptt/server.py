"""Localhost HTTP control server for the AHK front-end.

Protocol (kept dead simple — plain UTF-8 text bodies, status codes for errors):

    GET  /ping      200 "<active device>" when ready, 503 while loading, 500 on failed startup
    POST /start     begin mic capture (idempotent)
    POST /stop      stop capture, transcribe, respond with the final text
    POST /cancel    stop capture, discard audio
    POST /shutdown  graceful exit

The server binds immediately so the front-end can poll /ping while the model
downloads/compiles; /start etc. return 503 until the pipeline is ready.
"""

from __future__ import annotations

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from . import model_fetch, postprocess
from .audio import Recorder
from .config import Settings
from .transcriber import Transcriber

# Utterances shorter than this are discarded: Whisper hallucinates on
# near-empty input, and sub-0.2s can't contain a word anyway.
MIN_AUDIO_SECONDS = 0.2

# Speech-vs-noise gate. Absolute thresholds fail on quiet mics (real speech
# measured RMS 0.0056 on this machine, below any sane fixed gate), so the test
# is dynamics-based: speech recordings contain loud windows (the words) AND
# quiet windows (the pauses around them, incl. the press-key-then-speak gap),
# while ambient noise is flat. Requires the 95th-pct 100ms window to be both
# above the absolute floor (config silence_rms) and PEAK_OVER_FLOOR x the
# 20th-pct window. All three numbers are logged per utterance for tuning.
PEAK_OVER_FLOOR = 2.0


def _speech_stats(audio: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
    """(overall RMS, 95th-pct window RMS, 20th-pct window RMS), 100ms windows."""
    if not len(audio):
        return 0.0, 0.0, 0.0
    rms = float(np.sqrt(np.mean(np.square(audio))))
    win = max(1, sample_rate // 10)
    n = len(audio) // win
    if n < 2:
        return rms, rms, rms
    wrms = np.sqrt(np.mean(np.square(audio[: n * win].reshape(n, win)), axis=1))
    return rms, float(np.percentile(wrms, 95)), float(np.percentile(wrms, 20))


class _State:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger
        self.status = "loading"  # loading -> ready | failed
        self.error = ""
        self.recorder: Recorder | None = None
        self.transcriber: Transcriber | None = None
        self.cleanup = None  # CleanupPass when [cleanup] enabled
        self.media = None  # MediaPauser when [media] pause_on_record
        self.lock = threading.Lock()


def _make_handler(state: _State, server_ref: dict):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code: int, body: str = "") -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):  # route http.server noise to our logger
            state.logger.debug("http: " + fmt, *args)

        def do_GET(self):
            if self.path != "/ping":
                return self._reply(404, "unknown path")
            if state.status == "ready":
                body = state.transcriber.device
                if state.cleanup is not None:
                    body += f" (cleanup: {state.cleanup.device})"
                return self._reply(200, body)
            if state.status == "loading":
                return self._reply(503, "loading")
            return self._reply(500, state.error or "startup failed")

        def do_POST(self):
            try:
                handler = {
                    "/start": self._start,
                    "/stop": self._stop,
                    "/cancel": self._cancel,
                    "/shutdown": self._shutdown,
                }.get(self.path)
                if handler is None:
                    return self._reply(404, "unknown path")
                handler()
            except Exception as exc:
                state.logger.exception("error handling %s", self.path)
                self._reply(500, str(exc))

        def _start(self):
            if state.status != "ready":
                return self._reply(503, state.error or "not ready")
            with state.lock:
                if not state.recorder.recording:
                    # Pause music BEFORE opening the mic so it isn't recorded.
                    if state.media is not None:
                        state.media.pause_playing()
                    state.recorder.start()
            self._reply(200, "recording")

        def _stop(self):
            if state.status != "ready":
                return self._reply(503, state.error or "not ready")
            with state.lock:
                if not state.recorder.recording:
                    return self._reply(409, "not recording")
                audio = state.recorder.stop()
                # Mic is closed — music can come back while we transcribe.
                if state.media is not None:
                    state.media.resume()

            audio_s = len(audio) / state.settings.sample_rate
            rms, peak, floor = _speech_stats(audio, state.settings.sample_rate)
            speechy = peak >= state.settings.silence_rms and peak >= PEAK_OVER_FLOOR * floor
            if audio_s < MIN_AUDIO_SECONDS or not speechy:
                state.logger.info(
                    "utterance discarded (audio=%.2fs rms=%.4f peak=%.4f floor=%.4f, "
                    "need peak>=%.4f and peak>=%.1fx floor)",
                    audio_s, rms, peak, floor,
                    state.settings.silence_rms, PEAK_OVER_FLOOR,
                )
                return self._reply(200, "")

            t0 = time.perf_counter()
            raw = state.transcriber.transcribe(audio)
            whisper_s = time.perf_counter() - t0
            text = postprocess.apply(raw)  # cleanup step logs its own timing
            total_s = time.perf_counter() - t0
            state.logger.info(
                "utterance: audio=%.2fs rms=%.4f peak=%.4f floor=%.4f "
                "whisper=%.2fs total=%.2fs rtf=%.2f device=%s chars=%d",
                audio_s, rms, peak, floor, whisper_s, total_s,
                whisper_s / audio_s, state.transcriber.device, len(text),
            )
            self._reply(200, text)

        def _cancel(self):
            with state.lock:
                if state.recorder is not None:
                    state.recorder.cancel()
                if state.media is not None:
                    state.media.resume()
            self._reply(200, "cancelled")

        def _shutdown(self):
            state.logger.info("shutdown requested")
            self._reply(200, "bye")
            threading.Thread(target=server_ref["server"].shutdown, daemon=True).start()

    return Handler


def run(settings: Settings, logger: logging.Logger) -> None:
    state = _State(settings, logger)
    server_ref: dict = {}
    server = ThreadingHTTPServer(
        (settings.host, settings.port), _make_handler(state, server_ref)
    )
    server_ref["server"] = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("listening on http://%s:%d", settings.host, settings.port)

    try:
        model_dir = model_fetch.fetch(settings, logger)
        state.recorder = Recorder(settings.sample_rate, settings.mic_index)
        if settings.pause_media:
            from .media import MediaPauser

            state.media = MediaPauser(logger)
        state.transcriber = Transcriber(model_dir, settings.device_order, logger)

        if settings.cleanup_enabled:
            # Cleanup is best-effort: if the model can't load, dictation still
            # works — just without the LLM pass.
            try:
                from .cleanup import CleanupPass

                cleanup_dir = model_fetch.fetch_cleanup(settings, logger)
                state.cleanup = CleanupPass(
                    cleanup_dir,
                    settings.cleanup_device_order,
                    settings.cleanup_max_new_tokens,
                    logger,
                )
                postprocess.STEPS.append(state.cleanup)
            except Exception:
                logger.exception("cleanup pass disabled (failed to initialize)")

        state.status = "ready"
        cleanup_dev = state.cleanup.device if state.cleanup else "off"
        logger.info(
            "ready — active device: %s (cleanup: %s)",
            state.transcriber.device, cleanup_dev,
        )
        print(
            f"active device: {state.transcriber.device} (cleanup: {cleanup_dev})",
            flush=True,
        )
    except Exception as exc:
        state.status = "failed"
        state.error = f"{type(exc).__name__}: {exc}"
        logger.exception("startup failed")

    thread.join()  # returns when /shutdown triggers server.shutdown()
    logger.info("server stopped")
