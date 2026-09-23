#!/usr/bin/env python3
"""Serialize ReasoningFact JSON to Turtle and print or write it.

Usage:
    serialize-facts-turtle.py [FILE ...] [--output OUT]

Reads one or more JSON files (a single fact, a list of facts, or an object
with a ``facts`` array); with no file argument, reads stdin. Read-only: this
script never touches registry, ontology, Gateway, or SAP.

Exit codes: 0 success, 1 input parse/validation failure, 2 usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (str(REPO_ROOT), str(REPO_ROOT / "agent")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sap_nexus_agent.fact_turtle import facts_to_turtle  # noqa: E402


def extract_facts(payload: object) -> list[dict]:
    """Normalize the accepted input shapes to a list of fact mappings."""
    if isinstance(payload, dict) and "factId" in payload:
        return [payload]
    if isinstance(payload, dict) and isinstance(payload.get("facts"), list):
        return [item for item in payload["facts"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("input is not a fact, a list of facts, or {'facts': [...]}")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    output: str | None = None
    files: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--output":
            if index + 1 >= len(args):
                print("--output requires a path", file=sys.stderr)
                return 2
            output = args[index + 1]
            index += 2
            continue
        if arg.startswith("--output="):
            output = arg.split("=", 1)[1]
        elif arg.startswith("--"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            return 2
        else:
            files.append(arg)
        index += 1

    try:
        facts: list[dict] = []
        if not files:
            facts.extend(extract_facts(json.load(sys.stdin)))
        else:
            for name in files:
                with open(name, encoding="utf-8") as handle:
                    facts.extend(extract_facts(json.load(handle)))
        turtle = facts_to_turtle(facts)
    except (json.JSONDecodeError, ValueError, KeyError, OSError) as exc:
        print(f"INPUT_INVALID: {exc}", file=sys.stderr)
        return 1

    if output:
        Path(output).write_text(turtle, encoding="utf-8")
        print(f"Turtle written: {output} ({len(facts)} fact(s))")
    else:
        print(turtle, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
