"""Launcher script.

This is both the way to run Spyder from source (`python run_spyder.py`) and the
entry point PyInstaller bundles.
"""

import sys

from spyder.main import main

if __name__ == "__main__":
    sys.exit(main())
