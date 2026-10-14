"""Deterministic analysis runtime: wire in (facts+plan), wire out (results).

This module is both a library (``run_analysis``) and a controlled
stdin/stdout subprocess entry (``python -m ...analysis_runtime``). The
child process needs no credentials and performs no network access.
"""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from typing import Any

from . import operators as operator_module
from .contracts import NodeResult, TypedFieldValue
from .fact_normalizer import normalize
from .release import pin_release

_CREDENTIAL_ENV_PREFIXES = ("SAP_NEXUS_APPROVAL_TOKEN", "SAP_NEXUS_GATEWAY_URL")
_CREDENTIAL_ENV_EXACT = frozenset({"SAP_NEXUS_PRINCIPAL"})


def sanitize_child_environment(env: dict[str, str]) -> dict[str, str]:
    """Remove gateway/credential/principal values inherited from a parent."""
    return {
        key: value
        for key, value in env.items()
        if key not in _CREDENTIAL_ENV_EXACT
        and not any(key == prefix for prefix in _CREDENTIAL_ENV_PREFIXES)
    }


def _node_results(raw: list[dict[str, Any]]) -> tuple[NodeResult, ...]:
    return tuple(
        NodeResult(
            node_id=row["nodeId"],
            capability_id=row["capabilityId"],
            parameters=dict(row.get("parameters", {})),
            gateway_trace_id=row.get("gatewayTraceId"),
            executed_at=row["executedAt"],
            data=dict(row.get("data", {})),
        )
        for row in raw
    )


def _rows_from_facts(facts) -> list:
    return [
        SimpleNamespace(
            fact_id=fact.fact_id,
            fields=fact.fields,
            unit=fact.unit,
            unit_value=fact.unit["value"] if fact.unit else None,
        )
        for fact in facts
    ]


def _rows_from_generic(rows: list[dict[str, Any]]):
    adapted = []
    for row in rows:
        fields = {
            name: TypedFieldValue(value=value["value"], semantic_type=value["semanticType"])
            for name, value in row.get("fields", {}).items()
        }
        unit_value = row.get("unit")
        adapted.append(
            SimpleNamespace(
                fact_id=row.get("factId", "node"),
                fields=fields,
                unit={"field": "unit", "value": unit_value} if unit_value else None,
                unit_value=unit_value,
            )
        )
    return adapted


def _to_generic_rows(result_rows) -> list[dict[str, Any]]:
    rows = []
    for row in result_rows:
        if "groupKey" in row:
            rows.append(row)  # already an operator output row
        else:
            rows.append(row)
    return rows


def _dispatch(node: dict[str, Any], inputs, version: str, conflicts: tuple[str, ...]):
    params = dict(node.get("params", {}))
    func = getattr(operator_module, node["operatorId"])
    return func(node["nodeId"], tuple(inputs), params, node.get("operatorVersion", version), conflicts)


def run_analysis(wire: dict[str, Any], pinned: Any | None = None) -> dict[str, Any]:
    if wire.get("wireVersion") != 1:
        return {"wireVersion": 1, "status": "failed", "facts": [], "results": [],
                "uncoveredConclusions": [], "limits": {},
                "semanticSnapshotId": None, "reasons": ["WIRE_VERSION_UNSUPPORTED"]}
    if pinned is None:
        repo_root = os.environ.get("SAP_NEXUS_AGENT_ROOT")
        from pathlib import Path

        pinned = pin_release(Path(repo_root) if repo_root else Path.cwd())

    release = wire.get("release", {})
    if (
        release.get("semanticSnapshotId") != pinned.package.semantic_snapshot_id
        or release.get("registrySnapshotId") != pinned.package.registry_snapshot_id
    ):
        return {"wireVersion": 1, "status": "failed", "facts": [], "results": [],
                "uncoveredConclusions": [], "limits": {},
                "semanticSnapshotId": release.get("semanticSnapshotId"),
                "reasons": ["RELEASE_MISMATCH"]}

    from .bounds import BOUNDS
    normalization = normalize(
        _node_results(wire.get("nodeResults", [])), pinned,
        run_id=wire.get("runId", "run"),
        max_rows=BOUNDS.max_rows,
    )
    facts = normalization.facts
    conflicts = normalization.conflicts

    plan_nodes = wire["analysisPlan"]["nodes"]
    by_id: dict[str, Any] = {}
    state: dict[str, int] = {}

    def visit(node_id: str):
        if state.get(node_id) == 1:
            raise ValueError("analysis DAG cycle")
        if state.get(node_id) == 2:
            return
        state[node_id] = 1
        node = next(n for n in plan_nodes if n["nodeId"] == node_id)
        inputs: list = []
        for dep in node.get("dependsOn", ()):
            visit(dep)
        fact_refs = [i for i in node.get("inputs", ()) if i.get("kind") == "factField"]
        node_refs = [i for i in node.get("inputs", ()) if i.get("kind") == "nodeRef"]
        if fact_refs and not node_refs:
            wanted_fields = {i["field"] for i in fact_refs}
            wanted_types = {i["factTypeId"] for i in fact_refs}
            selected = [
                f for f in facts
                if f.fact_type_ref in wanted_types and wanted_fields <= set(f.fields)
            ]
            inputs = _rows_from_facts(tuple(selected))
        elif node_refs and not fact_refs:
            for ref in node_refs:
                upstream = by_id[ref["nodeId"]]
                inputs.extend(_rows_from_generic(list(upstream.rows)))
        else:
            fact_rows = _rows_from_facts(tuple(
                f for f in facts
                if any(f.fact_type_ref == i.get("factTypeId") for i in fact_refs)
            ))
            for ref in node_refs:
                fact_rows.extend(_rows_from_generic(list(by_id[ref["nodeId"]].rows)))
            inputs = fact_rows
        state[node_id] = 2
        by_id[node_id] = _dispatch(node, inputs, pinned.compiler_version, conflicts)

    for node in plan_nodes:
        visit(node["nodeId"])

    results = [by_id[n["nodeId"]].to_dict() for n in plan_nodes]
    statuses = {r["status"] for r in results}
    if {"failed", "rejected"} & statuses:
        overall = "failed" if "failed" in statuses else "partial"
    elif {"capability_gap"} & statuses:
        overall = "capability_gap"
    elif {"semantic_gap"} & statuses:
        overall = "semantic_gap"
    elif {"clarification"} & statuses:
        overall = "clarification"
    elif "partial" in statuses or any(r["partial"] for r in results):
        overall = "partial"
    else:
        overall = "complete"

    uncovered = []
    if overall != "complete":
        for conclusion in wire.get("requestedConclusions", ()):
            uncovered.append({
                "conclusionId": conclusion["id"],
                "reason": f"ANALYSIS_{overall.upper()}",
            })

    return {
        "wireVersion": 1,
        "status": overall,
        "facts": [fact.to_dict() for fact in facts],
        "results": results,
        "uncoveredConclusions": uncovered,
        "limits": {},
        "semanticSnapshotId": wire.get("release", {}).get("semanticSnapshotId"),
        "excludedRows": [
            exclusion.to_dict()
            for result in by_id.values()
            for exclusion in result.excluded_rows
        ],
        "conflicts": list(conflicts),
        "normalizationExclusions": [e.to_dict() for e in normalization.exclusions],
    }


def _main_plan(raw: bytes) -> int:
    import json as _json
    from pathlib import Path

    request = _json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError(f"non-finite constant: {value}")
    ))
    from .planner_service import plan_request

    repo_root = Path(
        os.environ.get("SAP_NEXUS_AGENT_ROOT")
        or Path(__file__).resolve().parents[3]
    )
    envelope = plan_request(request, repo_root)
    _json.dump(envelope, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if envelope["status"] in {"planned", "complete", "partial"} else (
        3 if envelope["status"] == "rejected" else 1
    )


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--mode" and sys.argv[2] == "plan":
        return _main_plan(sys.stdin.buffer.read())
    raw = sys.stdin.buffer.read()
    try:
        wire = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite constant: {value}")
        ))
    except (ValueError, json.JSONDecodeError):
        print(json.dumps({"status": "failed", "reasons": ["MALFORMED_WIRE"]}))
        return 1
    try:
        envelope = run_analysis(wire)
    except Exception as exc:  # noqa: BLE001 - boundary: structured failure
        print(json.dumps({"status": "failed", "reasons": [f"RUNTIME_ERROR:{exc}"]}))
        return 1
    json.dump(envelope, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
