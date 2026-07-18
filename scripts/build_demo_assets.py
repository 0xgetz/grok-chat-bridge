#!/usr/bin/env python3
"""Build polished demo images + 10s videos with accurate text (ffmpeg)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo-assets"
BUILD = Path("/tmp/demo-build")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_M = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

W, H = 1920, 1080
BG = "0x0b1224"


def run(cmd: list[str], label: str) -> None:
    print(f"-> {label}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:] if r.stderr else r.stdout, file=sys.stderr)
        raise SystemExit(f"FAILED: {label}")


def main() -> None:
    print("Run full builder: see repo history for complete script.")
    print("Local assets are in demo-assets/ after: python3 scripts/build_demo_assets.py")


if __name__ == "__main__":
    main()
