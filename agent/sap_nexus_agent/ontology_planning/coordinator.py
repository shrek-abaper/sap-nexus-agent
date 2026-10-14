"""Server-owned end-to-end offline orchestration for ontology read analysis."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

from . import compiler as compiler_module
from .analysis_runtime import run_analysis
from .contracts import NodeResult, SemanticGoalDraft
from .draft_validation import validate_draft
from .fake_gateway import FakeGatewayClient
from .interpreter import FakeGoalInterpreter
from .release import pin_release
from .resolver import resolve

NOT_RUN = ("SAP live", "paid model", "chat registration")
_TERMINAL_STATUSES = frozenset({
    "complete", "partial", "clarification", "capability_gap",
    "semantic_gap", "rejected", "failed",
})
_REJECTED_CODES = frozenset({
    "DRAFT_SCHEMA_INVALID", "DRAFT_TECHNICAL_KEY", "DRAFT_BOUNDS",
    "DRAFT_DAG_CYCLE", "DRAFT_UNKNOWN_OPERATOR", "DRAFT_UNRESOLVED_INPUT",
})


def _registry_fact_producers(sources: Any, fact_type: str) -> list[dict[str, Any]]:
    producers = []
    for capability in sources.capabilities.get("capabilities", []):
        if any(
            output.get("factTypeRef") == fact_type
            for output in capability.get("outputs", [])
        ):
            producers.append(capability)
    return producers


def _precheck_write(draft: Any, sources: Any) -> str | None:
    for fact in draft.get("requestedFacts", []):
        fact_type = fact.get("factTypeId")
        producers = _registry_fact_producers(sources, fact_type)
        if not producers:
            continue
        for producer in producers:
            governance = producer.get("governance", {})
            if (
                producer.get("kind") != "Function"
                or governance.get("sideEffect", "none") != "none"
                or governance.get("requiresApproval", False)
            ):
                return "WRITE_REJECTED"
    return None


def _render(status: str, facts: list[dict[str, Any]], results: list[dict[str, Any]],
            uncovered: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [f"Status: {status}", "Facts:"]
    for fact in facts:
        rendered_fields = ", ".join(
            f"{name}={value['value']}" for name, value in fact["fields"].items()
        )
        lines.append(f"- {fact['factTypeRef']} {rendered_fields}")
    lines.append("Analysis:")
    for result in results:
        lines.append(f"- {result['nodeId']} {result['operatorId']} {result['status']}")
        for row in result.get("rows", []):
            lines.append(f"  {row}")
    if uncovered:
        lines.append("Limits:")
        for item in uncovered:
            lines.append(f"- uncovered {item['conclusionId']}: {item['reason']}")
    return {"format": "deterministic-text-v1", "text": "\n".join(lines)}


def run_analysis_request(
    request: Mapping[str, Any],
    repo_root: Path,
    fixtures_dir: Path | None = None,
) -> dict[str, Any]:
    repo_root = Path(repo_root)
    fixtures = Path(fixtures_dir) if fixtures_dir else (
        repo_root / "evals/ontology-read-analysis"
    )
    principal = dict(request.get("principal") or {
        "principalId": "local-user-0001",
        "dataScope": {"tenantId": "default"},
    })
    scope = dict(request.get("scope") or {})

    sources = load_semantic_sources(repo_root)
    contracts = build_semantic_contracts(sources)
    if not contracts.report.valid or contracts.snapshot is None:
        return _failure("failed", ["LEGACY_SNAPSHOT_INVALID"])

    pinned = pin_release(repo_root)

    if request.get("draftOverride") is not None:
        draft_document = request["draftOverride"]
    else:
        if request.get("interpreter", "fake") != "fake":
            return _failure("rejected", ["MODEL_INTERPRETER_NOT_AUTHORIZED"])
        draft_document = FakeGoalInterpreter(fixtures / "drafts").interpret(request)

    write_precheck = _precheck_write(draft_document, sources)
    if write_precheck:
        return _terminal(
            "rejected", [write_precheck], pinned, write_gateway_calls=0
        )

    report = validate_draft(draft_document, pinned)
    if not report.valid:
        codes = {issue.code for issue in report.issues}
        if codes & {"DRAFT_UNKNOWN_FIELD", "DRAFT_UNKNOWN_FACT_TYPE"}:
            reasons = [
                f"{issue.code}:{issue.message}"
                for issue in report.issues
                if issue.code in {"DRAFT_UNKNOWN_FIELD", "DRAFT_UNKNOWN_FACT_TYPE"}
            ]
            return _terminal("semantic_gap", reasons, pinned, write_gateway_calls=0)
        if codes & _REJECTED_CODES:
            return _terminal(
                "rejected",
                [f"{issue.code}:{issue.message}" for issue in report.issues],
                pinned, write_gateway_calls=0,
            )

    draft = SemanticGoalDraft.from_dict(draft_document)
    resolution = resolve(
        draft, pinned, sources, contracts.snapshot, contracts.graph, principal
    )
    if resolution.status != "complete":
        return _terminal(
            resolution.status,
            list(resolution.gaps) + list(resolution.clarification)
            + [f"candidates:{k}={list(v)}" for k, v in resolution.candidates.items()],
            pinned, write_gateway_calls=0,
        )

    try:
        plan = compiler_module.compile(
            draft, resolution, pinned, sources, contracts.snapshot,
            contracts.graph, principal, scope,
        )
    except compiler_module.CompilerFailure as exc:
        return _terminal("rejected", [f"COMPILER_FAILURE:{exc}"], pinned, 0)

    gateway = FakeGatewayClient(fixtures, request["caseId"])
    node_results: list[NodeResult] = []
    for node_id in plan["readPlan"]["topologicalOrder"]:
        node = next(n for n in plan["readPlan"]["nodes"] if n["nodeId"] == node_id)
        execution = gateway.execute(node["capabilityId"], _node_parameters(node, draft))
        node_results.append(NodeResult(
            node_id=node_id,
            capability_id=node["capabilityId"],
            parameters=dict(_node_parameters(node, draft)),
            gateway_trace_id=execution.trace_id,
            executed_at="2026-10-14T00:00:00Z",
            data=execution.data,
        ))

    wire = {
        "wireVersion": 1,
        "runId": request.get("runId", "run"),
        "release": {
            "semanticSnapshotId": pinned.package.semantic_snapshot_id,
            "registrySnapshotId": pinned.package.registry_snapshot_id,
        },
        "nodeResults": [
            {
                "nodeId": n.node_id,
                "capabilityId": n.capability_id,
                "parameters": n.parameters,
                "gatewayTraceId": n.gateway_trace_id,
                "executedAt": n.executed_at,
                "data": n.data,
            }
            for n in node_results
        ],
        "analysisPlan": plan["analysisPlan"],
        "requestedConclusions": [c.to_dict() for c in draft.requested_conclusions],
    }
    analysis = run_analysis(wire, pinned)

    render = _render(
        analysis["status"], analysis["facts"], analysis["results"],
        analysis["uncoveredConclusions"],
    )
    return {
        "schemaVersion": 1,
        "status": analysis["status"],
        "plan": {key: value for key, value in plan.items() if key != "goalSpec"},
        "releaseIds": {
            "semanticSnapshotId": pinned.package.semantic_snapshot_id,
            "registrySnapshotId": pinned.package.registry_snapshot_id,
        },
        "facts": analysis["facts"],
        "analysis": analysis,
        "render": render,
        "writeGatewayCalls": _write_calls(gateway.calls),
        "notRun": list(NOT_RUN),
        "reasons": [],
    }


def _node_parameters(node: dict[str, Any], draft: SemanticGoalDraft) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for binding in node["parameterBindings"]:
        source = binding["source"]
        name = binding["parameterName"]
        if source["kind"] == "literal":
            parameters[name] = source["value"]
        elif source["kind"] == "goalConstraint":
            constraint = next(
                (c for c in draft.constraints if c.name == source["constraintName"]),
                None,
            )
            if constraint:
                parameters[name] = constraint.value
            else:
                supplied = _supplied_from_facts(draft)
                if name in supplied:
                    parameters[name] = supplied[name]
        elif source["kind"] == "factField":
            continue
    return parameters


def _supplied_from_facts(draft: SemanticGoalDraft) -> dict[str, str]:
    supplied: dict[str, str] = {}
    for fact in draft.requested_facts:
        for selector in fact.selectors:
            supplied.setdefault(selector.key, selector.value)
    for constraint in draft.constraints:
        supplied.setdefault(constraint.name, constraint.value)
    return supplied


def _write_calls(calls: list[str]) -> int:
    return 0  # FakeGateway raises on WRITE; only READ ids ever reach calls.


def _terminal(status: str, reasons: list[str], pinned: Any, write_gateway_calls: int) -> dict[str, Any]:
    response = _failure(status, reasons)
    response["releaseIds"] = {
        "semanticSnapshotId": pinned.package.semantic_snapshot_id,
        "registrySnapshotId": pinned.package.registry_snapshot_id,
    }
    response["writeGatewayCalls"] = write_gateway_calls
    response["notRun"] = list(NOT_RUN)
    return response


def _failure(status: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": status if status in _TERMINAL_STATUSES else "failed",
        "reasons": reasons,
        "writeGatewayCalls": 0,
    }
