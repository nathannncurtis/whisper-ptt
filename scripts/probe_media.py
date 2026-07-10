"""Read-only diagnostic: list Windows media sessions and their playback state.

    .venv\\Scripts\\python scripts\\probe_media.py
"""

import asyncio


async def main() -> None:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
    )

    manager = await Manager.request_async()
    sessions = manager.get_sessions()
    if not len(sessions):
        print("no media sessions")
        return
    for s in sessions:
        info = s.get_playback_info()
        status = info.playback_status.name if info else "?"
        try:
            props = await s.try_get_media_properties_async()
            title = props.title
        except Exception:
            title = "?"
        print(f"{s.source_app_user_model_id}: {status} — {title}")


if __name__ == "__main__":
    asyncio.run(main())
