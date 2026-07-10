"""Entry point: `python -m whisper_ptt [--config path] [--fetch-model]`."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import load
from .logging_setup import setup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisper-ptt")
    parser.add_argument("--config", default="config.ini", help="path to config.ini")
    parser.add_argument(
        "--fetch-model", action="store_true",
        help="download/convert the configured model, then exit",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    settings = load(args.config)
    logger = setup(settings.log_dir, settings.log_level)

    if args.fetch_model:
        from . import model_fetch

        model_fetch.fetch(settings, logger)
        if settings.cleanup_enabled:
            model_fetch.fetch_cleanup(settings, logger)
        return 0

    from . import server

    server.run(settings, logger)
    return 0


if __name__ == "__main__":
    sys.exit(main())
