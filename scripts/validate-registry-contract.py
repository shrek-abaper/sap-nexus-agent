#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from validate_registry_contract import load_registry_contract, validate_registry_contract


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: validate-registry-contract.py <registry-file>", file=sys.stderr)
        return 2
    contract = load_registry_contract(Path(args[0]))
    errors = validate_registry_contract(contract, repo_root=Path("."))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Registry contract valid: {args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
