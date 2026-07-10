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
SILENCE_PEAK = 1e-4


class _State:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger
        self.status = "loading"  # loading -> ready | failed
        self.error = ""
        self.recorder: Recorder | None = None
        self.transcriber: Transcriber | None = None
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
                return self._reply(200, state.transcriber.device)
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
                    state.recorder.start()
            self._reply(200, "recording")

        def _stop(self):
            if state.status != "ready":
                return self._reply(503, state.error or "not ready")
            with state.lock:
                if not state.recorder.recording:
                    return self._reply(409, "not recording")
                audio = state.recorder.stop()

            audio_s = len(audio) / state.settings.sample_rate
            if audio_s < MIN_AUDIO_SECONDS or np.abs(audio).max() < SILENCE_PEAK:
                state.logger.info("utterance discarded (%.2fs, silent/too short)", audio_s)
                return self._reply(200, "")

            t0 = time.perf_counter()
            text = postprocess.apply(state.transcriber.transcribe(audio))
            proc_s = time.perf_counter() - t0
            state.logger.info(
                "utterance: audio=%.2fs proc=%.2fs rtf=%.2f device=%s chars=%d",
                audio_s, proc_s, proc_s / audio_s, state.transcriber.device, len(text),
            )
            self._reply(200, text)

        def _cancel(self):
            with state.lock:
                if state.recorder is not None:
                    state.recorder.cancel()
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
        state.transcriber = Transcriber(model_dir, settings.device_order, logger)
        state.status = "ready"
        logger.info("ready — active device: %s", state.transcriber.device)
        print(f"active device: {state.transcriber.device}", flush=True)
    except Exception as exc:
        state.status = "failed"
        state.error = f"{type(exc).__name__}: {exc}"
        logger.exception("startup failed")

    thread.join()  # returns when /shutdown triggers server.shutdown()
    logger.info("server stopped")
