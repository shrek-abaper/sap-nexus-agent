#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

"$PYTHON_BIN" scripts/validate-semantic-planning-contract.py
"$PYTHON_BIN" -m pytest agent/tests
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/pr_create_cases.json
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/matcher_cases.yaml
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/dry_run_cases.yaml
openspec validate --all --strict
