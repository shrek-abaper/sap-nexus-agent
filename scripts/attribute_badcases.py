#!/usr/bin/env python3
"""Attribute annotated decision traces into bad-case review artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from sap_nexus_agent.badcase_pipeline import run_pipeline  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bad-case attribution pipeline")
    parser.add_argument("--traces", required=True, help="Phase-1 decision trace JSONL")
    parser.add_argument("--annotations", required=True, help="human annotations JSON")
    parser.add_argument(
        "--output-dir", default=str(REPO_ROOT / "runtime/badcase-review"),
    )
    args = parser.parse_args(argv)

    summary = run_pipeline(
        traces_path=Path(args.traces),
        annotations_path=Path(args.annotations),
        output_dir=Path(args.output_dir),
    )
    resolved_output = Path(args.output_dir).resolve()
    try:
        dir_label = str(resolved_output.relative_to(REPO_ROOT))
    except ValueError:
        dir_label = str(resolved_output)
    print(
        f"Badcase review: candidates={summary['candidates']} "
        f"clusters={summary['clusters']} corrections={summary['corrections']} | "
        f"dir={dir_label}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
