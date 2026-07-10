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

# Live transcription: while recording, a worker re-transcribes the growing
# audio every PARTIAL_INTERVAL seconds so that on key-release there is little
# left to do. If the cached pass covers all but PARTIAL_REUSE_TAIL_S of the
# final audio (i.e. only trailing silence arrived since), the final Whisper
# run is skipped entirely and we go straight to postprocess/cleanup.
PARTIAL_INTERVAL = 1.5
PARTIAL_MIN_NEW_S = 0.5  # don't re-run for less than this much new audio
PARTIAL_REUSE_TAIL_S = 0.6


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


class _StreamJob:
    """Buffer between the cleanup generation thread and /delta polls."""

    def __init__(self):
        self._chunks: list[str] = []
        self._done = False
        self._lock = threading.Lock()

    def emit(self, chunk: str) -> None:
        with self._lock:
            self._chunks.append(chunk)

    def finish(self) -> None:
        with self._lock:
            self._done = True

    def take(self) -> tuple[str, bool]:
        with self._lock:
            delta = "".join(self._chunks)
            self._chunks.clear()
            return delta, self._done


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
        # Live-transcription state: (samples_covered, text) of the newest
        # background pass; asr_lock serializes Whisper between the worker and
        # the /stop handler.
        self.partial: tuple[int, str] = (0, "")
        self.partial_stop: threading.Event | None = None
        self.asr_lock = threading.Lock()
        self.job: _StreamJob | None = None  # in-flight cleanup stream


def _partial_worker(state: _State, stop_evt: threading.Event) -> None:
    sample_rate = state.settings.sample_rate
    last_n = 0
    while not stop_evt.wait(PARTIAL_INTERVAL):
        recorder = state.recorder
        if recorder is None or not recorder.recording:
            break
        audio = recorder.snapshot()
        if (len(audio) - last_n) / sample_rate < PARTIAL_MIN_NEW_S:
            continue
        try:
            with state.asr_lock:
                if stop_evt.is_set():  # /stop won the lock race — its job now
                    break
                text = state.transcriber.transcribe(audio)
            state.partial = (len(audio), text)
            last_n = len(audio)
            state.logger.debug(
                "live: %.1fs transcribed in background -> %d chars",
                len(audio) / sample_rate, len(text),
            )
        except Exception:
            state.logger.exception("live transcription pass failed")
            break


def _cleanup_job(state: _State, job: _StreamJob, text: str) -> None:
    """Run the LLM cleanup stream, falling back to the raw text on rejection."""
    try:
        final = state.cleanup.stream(text, job.emit)
        if final is None:
            job.emit(text)
    except Exception:
        state.logger.exception("cleanup job failed, emitting raw text")
        job.emit(text)
    finally:
        job.finish()


def _make_handler(state: _State, server_ref: dict):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code: int, body: str = "", headers: dict | None = None) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):  # route http.server noise to our logger
            state.logger.debug("http: " + fmt, *args)

        def do_GET(self):
            if self.path == "/delta":
                job = state.job
                if job is None:
                    return self._reply(404, "no stream in progress")
                delta, done = job.take()
                if done:
                    state.job = None
                return self._reply(200, delta, {"X-Done": "1" if done else "0"})
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
                    state.partial = (0, "")
                    state.partial_stop = threading.Event()
                    threading.Thread(
                        target=_partial_worker,
                        args=(state, state.partial_stop),
                        daemon=True,
                    ).start()
            self._reply(200, "recording")

        def _stop(self):
            if state.status != "ready":
                return self._reply(503, state.error or "not ready")
            with state.lock:
                if not state.recorder.recording:
                    return self._reply(409, "not recording")
                if state.partial_stop is not None:
                    state.partial_stop.set()
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
            with state.asr_lock:  # waits out any in-flight background pass
                n_cached, cached = state.partial
                tail_s = (len(audio) - n_cached) / state.settings.sample_rate
                if cached and tail_s <= PARTIAL_REUSE_TAIL_S:
                    state.logger.info("live transcript reused (tail=%.2fs)", tail_s)
                    raw = cached
                else:
                    if n_cached:
                        state.logger.info(
                            "live transcript stale (tail=%.2fs), full pass", tail_s
                        )
                    raw = state.transcriber.transcribe(audio)
            whisper_s = time.perf_counter() - t0
            text = postprocess.apply(raw)
            state.logger.info(
                "utterance: audio=%.2fs rms=%.4f peak=%.4f floor=%.4f "
                "whisper=%.2fs device=%s chars=%d",
                audio_s, rms, peak, floor, whisper_s,
                state.transcriber.device, len(text),
            )

            # Short or cleanup-less utterances: reply inline (status 200).
            # Otherwise: 202 + a background LLM stream the client polls via
            # /delta, typing words as they are generated.
            if (
                state.cleanup is None
                or not text
                or len(text.split()) < state.settings.cleanup_min_words
            ):
                return self._reply(200, text)

            job = _StreamJob()
            state.job = job
            threading.Thread(
                target=_cleanup_job, args=(state, job, text), daemon=True
            ).start()
            self._reply(202, "streaming; poll /delta")

        def _cancel(self):
            with state.lock:
                if state.partial_stop is not None:
                    state.partial_stop.set()
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
