#!/usr/bin/env python3
"""Standalone ACP smoke test (no package install required)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grok_chat_bridge.__main__ import _smoke_test
import argparse


async def main() -> None:
    args = argparse.Namespace(
        grok_bin=os.environ.get("GROK_BIN", "grok"),
        workdir=os.getcwd(),
        model=os.environ.get("GROK_MODEL"),
    )
    await _smoke_test(args)


if __name__ == "__main__":
    asyncio.run(main())
