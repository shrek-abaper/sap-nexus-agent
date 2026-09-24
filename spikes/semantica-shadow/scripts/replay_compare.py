#!/usr/bin/env python3
"""Replay eval cases on both paths and compare.

Path A: current deterministic rule path (parse_intent).
Path B: ontology path (SKOS recall, SHACL validation, precondition and
ODRL duty evaluation from query_shadow).

Drives intent cases (inventory/PO/SO/AR/AP) and WRITE approval cases
(PR: missing/expired/version mismatch/duplicate submit). Real master
values are substituted at the slot level from local-values.yaml
(gitignored); the committed report is masked.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPIKE_ROOT.parents[1]
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "agent"), str(Path(__file__).parent)]

import yaml  # noqa: E402
from sap_nexus_agent.intent import parse_intent  # noqa: E402

from query_shadow import (  # noqa: E402
    check_permission,
    evaluate_preconditions,
    load_graph,
    recall_capabilities,
    validate_input,
)

CASE_FILES = [
    "evals/inventory_availability_cases.yaml",
    "evals/purchase_order_cases.json",
    "evals/sales_order_list_cases.yaml",
    "evals/ar_open_items_cases.yaml",
    "evals/ap_open_items_cases.yaml",
    "evals/pr_create_cases.json",
]

# input name -> key in local-values.yaml
INPUT_VALUE_KEY = {
    "material": "material",
    "plant": "plant",
    "purchasing_group": "purchasingGroup",
    "vendor": "supplier",
    "customer": "customer",
    "customerNumber": "customer",
    "companyCode": "companyCode",
}

LOCAL_VALUES = yaml.safe_load(
    (SPIKE_ROOT / "local-values.yaml").read_text(encoding="utf-8")
)["values"]


def load_cases() -> list[dict]:
    cases: list[dict] = []
    for rel in CASE_FILES:
        payload = yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for case in payload["cases"]:
            case = dict(case)
            case["_file"] = rel
            cases.append(case)
    return cases


def _capability_inputs(cap_id: str) -> dict[str, dict]:
    registry = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    cap = next(c for c in registry["capabilities"] if c["capabilityId"] == cap_id)
    return {inp["name"]: inp for inp in cap["inputs"]}


def substitute_slots(cap_id: str, params: dict[str, str]) -> dict[str, Any]:
    """Apply real values per input; coerce numeric inputs to numbers."""
    inputs = _capability_inputs(cap_id)
    slots: dict[str, Any] = dict(params)
    for name, inp in inputs.items():
        if name in slots and name in INPUT_VALUE_KEY:
            slots[name] = LOCAL_VALUES[INPUT_VALUE_KEY[name]]
        if name in slots and inp.get("type") == "number":
            # Decimal so the SHACL value carries xsd:decimal (Python float
            # would surface as xsd:double).
            from decimal import Decimal

            slots[name] = Decimal(str(slots[name]))
    return slots


def snapshot_hash(slots: dict[str, Any]) -> str:
    encoded = json.dumps(slots, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ------------------------- WRITE approval scenarios -------------------------

def approval_scenario(case_id: str, snapshot: str) -> tuple[dict | None, str, bool]:
    """Return (approval record, caller hash, expected permission holds)."""
    future = "2099-01-01T00:00:00+00:00"
    past = "2020-01-01T00:00:00+00:00"
    base = {
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": snapshot,
        "expiresAt": future,
    }
    if "success" in case_id:
        return {**base, "status": "approved"}, snapshot, True
    if case_id == "pr-create-approval-missing":
        return None, snapshot, False
    if case_id == "pr-create-approval-expired":
        return {**base, "status": "approved", "expiresAt": past}, snapshot, False
    if case_id == "pr-create-approval-version-mismatch":
        return {**base, "status": "approved"}, snapshot + "-other", False
    if case_id == "pr-create-duplicate-submit":
        return {**base, "status": "executed"}, snapshot, False
    if case_id == "pr-create-sap-business-error":
        # Permission holds; the business error happens at execution, not gate.
        return {**base, "status": "approved"}, snapshot, True
    raise KeyError(case_id)


# ------------------------------ expected status ------------------------------

def expected_status_agrees(
    expected: dict, *, missing: list[str], permission: bool | None, case: dict
) -> bool:
    status = expected.get("status")
    if status == "success":
        return not missing and permission is not False
    if status == "clarification":
        return bool(missing)
    # failure: WRITE approval denied, or a gateway-supplied failure
    gateway_error = (case.get("gateway", {}).get("execute") or {}).get("errorType")
    validate_failure = (case.get("gateway", {}).get("validate") or {}).get(
        "success"
    ) is False
    return (
        permission is False
        or gateway_error not in (None, "NONE")
        or validate_failure
    )


def main() -> int:
    graph = load_graph()
    report: list[dict] = []
    mismatches: list[str] = []

    for case in load_cases():
        case_id = case["id"]
        utterance = case["userQuery"]
        result_a = parse_intent(utterance)
        matches = result_a.matched_intents
        record: dict[str, Any] = {
            "caseId": case_id,
            "file": case["_file"],
            "utterance": utterance,
        }

        if not matches:
            recall = recall_capabilities(graph, utterance)
            technical_override = (
                result_a.contains_rfc_name or result_a.contains_odata_override
            )
            # A technical-override rejection is enforcement, not missing
            # semantics: labels may still recall; the deterministic guard
            # correctly blocks.
            selection = (
                len(recall) >= 1 if technical_override else recall == []
            )
            record.update(
                {
                    "pathA": {"selected": None},
                    "rejectedByTechnicalGuard": technical_override,
                    "recallSize": len(recall),
                    "selectionAgreement": selection,
                }
            )
        else:
            match = matches[0]
            cap_id = match.capability_id
            slots = substitute_slots(cap_id, match.parameters)

            recall = recall_capabilities(graph, utterance)
            cap_registry = yaml.safe_load(
                (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
            )
            cap_entry = next(
                c for c in cap_registry["capabilities"] if c["capabilityId"] == cap_id
            )
            cap_node = "https://sap-nexus-agent.local/ontology#" + cap_entry[
                "ontologyIri"
            ].split(":", 1)[1]
            in_recall = any(c["capabilityNode"] == cap_node for c in recall)

            precond = evaluate_preconditions(graph, cap_id, slots)
            validations = {
                name: validate_input(graph, cap_id, name, value)["conforms"]
                for name, value in slots.items()
            }

            # Comparison basis: when the eval pins missingParameters, both
            # paths are compared to the governed contract (the raw engine
            # emits fact-satisfiable inputs too; the planner/execution
            # boundary reconciles them). Otherwise raw A vs B.
            expected_missing = case.get("expected", {}).get("missingParameters")
            if expected_missing is not None:
                missing_agreement = set(precond["missing"]) == set(
                    expected_missing
                )
                missing_basis = "governedExpected"
            else:
                missing_agreement = set(match.missing) == set(
                    precond["missing"]
                )
                missing_basis = "rawAvsB"

            record.update(
                {
                    "pathA": {
                        "selected": cap_id,
                        "rawMissing": sorted(match.missing),
                    },
                    "recallSize": len(recall),
                    "selectionAgreement": in_recall,
                    "missingB": sorted(precond["missing"]),
                    "missingBasis": missing_basis,
                    "missingAgreement": missing_agreement,
                    "validation": validations,
                    "validationConforms": all(validations.values()),
                }
            )

            # WRITE permission scenarios
            if cap_id == "MM.PR.CreateDraft" and not precond["missing"]:
                snapshot = snapshot_hash(slots)
                approval, caller_hash, expected_holds = approval_scenario(
                    case_id, snapshot
                )
                permission = check_permission(
                    graph,
                    cap_id,
                    approval or {},
                    parameter_snapshot_hash=caller_hash,
                )
                record.update(
                    {
                        "permissionHolds": permission["permission_holds"],
                        "permissionAgreement": permission["permission_holds"]
                        == expected_holds,
                    }
                )
            elif cap_id == "MM.PR.CreateDraft":
                record["permissionHolds"] = None  # blocked by preconditions
            else:
                record["permissionHolds"] = None

            record["expectedStatusAgreement"] = expected_status_agrees(
                case.get("expected", {}),
                missing=precond["missing"],
                permission=record.get("permissionHolds"),
                case=case,
            )

        for dimension in (
            "selectionAgreement",
            "missingAgreement",
            "validationConforms",
            "permissionAgreement",
            "expectedStatusAgreement",
        ):
            if dimension in record and not record[dimension]:
                mismatches.append(f"{case_id}:{dimension}")

        report.append(record)

    # full (unmasked) + masked committed report
    full = {"cases": report, "mismatches": mismatches}
    interim = SPIKE_ROOT / "reports" / "interim"
    interim.mkdir(parents=True, exist_ok=True)
    (interim / "replay-comparison.full.json").write_text(
        json.dumps(full, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    masked_text = json.dumps(full, ensure_ascii=False)
    for value in set(LOCAL_VALUES.values()):
        masked_text = masked_text.replace(str(value), "***")
    (SPIKE_ROOT / "reports" / "replay-comparison.json").write_text(
        json.dumps(json.loads(masked_text), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    total = len(report)
    print(f"cases: {total} | mismatches: {len(mismatches)}")
    for item in mismatches:
        print(" MISMATCH", item)
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
