"""PyInstaller entry point for the bundled backend exe."""

import sys

from whisper_ptt.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
