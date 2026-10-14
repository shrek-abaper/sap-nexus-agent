"""Offline evidence CLI for ontology-governed read analysis.

Usage:
    python -m sap_nexus_agent.ontology_planning.cli --case <case-id> [--json]
    python -m ...cli --request-file <path> [--json]

Exit codes: 0 typed terminal success, 1 internal failure, 2 usage, 3 rejected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .coordinator import run_analysis_request

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "evals/ontology-read-analysis"

# Typed terminal statuses that are not execution failures.
_NON_FAILURE = frozenset(
    {"complete", "partial", "clarification", "capability_gap", "semantic_gap"}
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ontology_planning.cli",
        description="Offline ontology-governed read analysis evidence runner.",
    )
    parser.add_argument("--case", dest="case_id")
    parser.add_argument("--request-file", dest="request_file")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--fixtures-dir", default=str(FIXTURES))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.case_id and not args.request_file:
        parser.error("one of --case/--request-file is required")
        return 2

    if args.request_file:
        request = json.loads(Path(args.request_file).read_text(encoding="utf-8"))
    else:
        request = {
            "schemaVersion": 1,
            "caseId": args.case_id,
            "interpreter": "fake",
            "slots": {},
        }

    try:
        response = run_analysis_request(
            request, Path(args.repo_root), Path(args.fixtures_dir)
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"status": "failed", "reasons": [f"INTERNAL:{exc}"]}))
        return 1

    status = response.get("status", "failed")
    if args.as_json:
        json.dump(response, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(response["render"]["text"] + "\n")

    if status == "rejected":
        return 3
    if status in _NON_FAILURE:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
