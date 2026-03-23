"""Package entrypoint for the Haotian skill-first runner."""

from __future__ import annotations

import argparse
import json

from haotian.runner import run_once


def main() -> None:
    """Execute the Haotian skill-first workflow entrypoint."""

    parser = argparse.ArgumentParser(description="Run one Haotian skill workflow cycle.")
    parser.add_argument("--date", default=None, help="Optional report date (YYYY-MM-DD).")
    args = parser.parse_args()
    summary = run_once(report_date=args.date)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
