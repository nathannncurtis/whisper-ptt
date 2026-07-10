"""Pause playing media while recording, resume afterwards.

Uses the Windows GlobalSystemMediaTransportControlsSessions API (the same
thing the keyboard media keys talk to), so it works with Spotify, browsers,
etc. Only sessions that were actually PLAYING get paused, and only those are
resumed — a session the user paused themselves stays paused.

Best-effort: any failure is logged and dictation proceeds normally.
"""

from __future__ import annotations

import asyncio
import logging


class MediaPauser:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._paused_apps: list[str] = []
        self._available = True
        try:
            import winsdk.windows.media.control  # noqa: F401
        except ImportError:
            self._available = False
            logger.warning("winsdk not installed — media pause disabled")

    def pause_playing(self) -> None:
        """Pause all currently playing sessions; remember which they were."""
        if not self._available:
            return
        try:
            self._paused_apps = asyncio.run(self._pause_all())
            if self._paused_apps:
                self.logger.info("paused media: %s", ", ".join(self._paused_apps))
        except Exception:
            self._paused_apps = []
            self.logger.exception("media pause failed")

    def resume(self) -> None:
        """Resume only the sessions this class paused."""
        if not self._available or not self._paused_apps:
            return
        try:
            resumed = asyncio.run(self._resume(self._paused_apps))
            if resumed:
                self.logger.info("resumed media: %s", ", ".join(resumed))
        except Exception:
            self.logger.exception("media resume failed")
        finally:
            self._paused_apps = []

    @staticmethod
    async def _sessions():
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )

        manager = await Manager.request_async()
        return manager.get_sessions()

    async def _pause_all(self) -> list[str]:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )

        paused = []
        for session in await self._sessions():
            info = session.get_playback_info()
            if info and info.playback_status == Status.PLAYING:
                if await session.try_pause_async():
                    paused.append(session.source_app_user_model_id)
        return paused

    async def _resume(self, app_ids: list[str]) -> list[str]:
        # Re-enumerate rather than holding session objects: sessions can be
        # invalidated between pause and resume.
        resumed = []
        for session in await self._sessions():
            if session.source_app_user_model_id in app_ids:
                if await session.try_play_async():
                    resumed.append(session.source_app_user_model_id)
        return resumed
