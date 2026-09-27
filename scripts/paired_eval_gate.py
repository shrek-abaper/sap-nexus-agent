#!/usr/bin/env python3
"""Paired eval gate CLI: compare Parent vs Candidate registry over offline suites."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from sap_nexus_agent.paired_eval import run_paired  # noqa: E402


def _format_regressed(report: dict) -> list[str]:
    parts = []
    for name in report["regressedSlis"]:
        sli = report["sli"][name]
        delta = sli["delta"]
        delta_text = "n/a" if delta is None else f"{delta:+.3f}"
        parts.append(
            f"{name} {sli['parent']['rate']:.3f}->{sli['candidate']['rate']:.3f} "
            f"delta={delta_text} ({sli.get('reason') or 'negative delta'})"
        )
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paired eval gate (Parent vs Candidate)")
    parser.add_argument("--parent", default="HEAD", help="git ref of the Parent registry")
    parser.add_argument(
        "--candidate",
        default=None,
        help="git ref of the Candidate registry; defaults to the live working tree",
    )
    parser.add_argument(
        "--output-dir", default=str(REPO_ROOT / "runtime/evals/results"),
    )
    args = parser.parse_args(argv)

    report, report_path = run_paired(
        repo_root=REPO_ROOT,
        parent_ref=args.parent,
        candidate_ref=args.candidate,
        output_dir=Path(args.output_dir),
    )
    compared = [
        name
        for name, sli in report["sli"].items()
        if sli["parent"]["total"] > 0 and sli["candidate"]["total"] > 0
    ]
    candidate_label = (
        report["candidate"]["commit"][:12]
        if report["candidate"]["ref"] != "worktree"
        else "worktree"
    )
    report_rel = report_path.relative_to(REPO_ROOT)
    if report["decision"] == "PASS":
        print(
            f"Paired eval: PASS | parent={report['parent']['commit'][:12]} | "
            f"candidate={candidate_label} | slis={','.join(compared)} | report={report_rel}"
        )
        return 0

    print(
        f"Paired eval: FAIL | parent={report['parent']['commit'][:12]} | "
        f"candidate={candidate_label} | "
        f"regressed={'; '.join(_format_regressed(report))} | report={report_rel}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
