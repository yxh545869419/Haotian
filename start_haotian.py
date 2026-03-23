"""Cross-platform one-click launcher for Haotian local deployment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _missing_dependency_message(missing_module: str) -> str:
    return (
        "Haotian 缺少运行依赖，当前无法启动。\n"
        f"缺失模块：{missing_module}\n"
        "请先在项目根目录执行：python -m pip install -e .\n"
        "如果你使用虚拟环境，请先激活对应环境后再执行上述命令。"
    )


def _load_commands():
    try:
        from haotian.cli.commands import serve_cli, serve_web  # noqa: E402
    except ModuleNotFoundError as exc:
        missing_module = exc.name or "unknown dependency"
        raise SystemExit(_missing_dependency_message(missing_module)) from exc
    return serve_cli, serve_web


def main() -> None:
    parser = argparse.ArgumentParser(description="One-click launcher for Haotian local modes.")
    parser.add_argument("--mode", choices=["web", "cli"], default="web", help="Startup mode.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for web mode.")
    parser.add_argument("--port", type=int, default=8765, help="Port for web mode.")
    args = parser.parse_args()
    serve_cli, serve_web = _load_commands()

    if args.mode == "web":
        serve_web(host=args.host, port=args.port)
        return
    serve_cli()


if __name__ == "__main__":
    main()
