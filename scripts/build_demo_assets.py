#!/usr/bin/env python3
"""Bootstrap: decode sibling .gz.b64 then exec full builder."""
from pathlib import Path
import base64, gzip, runpy, sys, os

here = Path(__file__).resolve().parent
b64_path = here / "build_demo_assets.py.gz.b64"
if not b64_path.exists():
    raise SystemExit(f"missing {b64_path}")
code = gzip.decompress(base64.b64decode(b64_path.read_text().strip()))
tmp = here / "_build_demo_assets_full.py"
tmp.write_bytes(code)
os.replace(tmp, Path(__file__).resolve())
sys.argv[0] = str(Path(__file__).resolve())
runpy.run_path(str(Path(__file__).resolve()), run_name="__main__")
