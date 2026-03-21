"""Cross-platform one-click launcher for Haotian local deployment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from haotian.cli.commands import serve_cli, serve_web  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="One-click launcher for Haotian local modes.")
    parser.add_argument("--mode", choices=["web", "cli"], default="web", help="Startup mode.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for web mode.")
    parser.add_argument("--port", type=int, default=8765, help="Port for web mode.")
    args = parser.parse_args()

    if args.mode == "web":
        serve_web(host=args.host, port=args.port)
        return
    serve_cli()


if __name__ == "__main__":
    main()
