"""Cross-platform one-click launcher for Haotian local deployment."""

from __future__ import annotations

import argparse
import json
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


def _load_runner():
    try:
        from haotian.runner import run_once  # noqa: E402
    except ModuleNotFoundError as exc:
        missing_module = exc.name or "unknown dependency"
        raise SystemExit(_missing_dependency_message(missing_module)) from exc
    return run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Haotian skill workflow cycle.")
    parser.add_argument("--date", default=None, help="Optional report date (YYYY-MM-DD).")
    args = parser.parse_args()
    run_once = _load_runner()
    summary = run_once(report_date=args.date)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
