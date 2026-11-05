#!/usr/bin/env python3
"""Source-tree and installed entry point; no third-party Python packages required."""
from pathlib import Path
import runpy
import sys

here = Path(__file__).resolve().parent
for directory in (here / "python", here.parent / "share/linkerbot-hand-tools/python"):
    if (directory / "hand_tools").is_dir():
        sys.path.insert(0, str(directory))
        break
runpy.run_module("hand_tools", run_name="__main__")
