"""Offline plan service: typed request + fixture draft -> read+analysis plan.

Used by the TS coordinator so the Python side stays the single planner
authority. Fake interpreter only; no model calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

from . import compiler as compiler_module
from .contracts import SemanticGoalDraft
from .coordinator import _failure, _precheck_write, _terminal
from .draft_validation import validate_draft
from .interpreter import FakeGoalInterpreter
from .release import pin_release
from .resolver import resolve

NOT_RUN = ("SAP live", "paid model", "chat registration")


def plan_request(
    request: dict[str, Any],
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

    if request.get("draftDocument") is not None:
        draft_document = request["draftDocument"]
    else:
        if request.get("interpreter", "fake") != "fake":
            return _failure("rejected", ["MODEL_INTERPRETER_NOT_AUTHORIZED"])
        draft_request = dict(request)
        if request.get("draftFile") is None and request.get("caseId"):
            draft_request["draftFile"] = f"{request['caseId']}.json"
        draft_document = FakeGoalInterpreter(fixtures / "drafts").interpret(draft_request)

    write_precheck = _precheck_write(draft_document, sources)
    if write_precheck:
        return _terminal("rejected", [write_precheck], pinned, 0)

    report = validate_draft(draft_document, pinned)
    if not report.valid:
        codes = {issue.code for issue in report.issues}
        if codes & {"DRAFT_UNKNOWN_FIELD", "DRAFT_UNKNOWN_FACT_TYPE"}:
            return _terminal(
                "semantic_gap",
                [f"{i.code}:{i.message}" for i in report.issues
                 if i.code in {"DRAFT_UNKNOWN_FIELD", "DRAFT_UNKNOWN_FACT_TYPE"}],
                pinned, 0,
            )
        rejected = {
            "DRAFT_SCHEMA_INVALID", "DRAFT_TECHNICAL_KEY", "DRAFT_BOUNDS",
            "DRAFT_DAG_CYCLE", "DRAFT_UNKNOWN_OPERATOR", "DRAFT_UNRESOLVED_INPUT",
        }
        if codes & rejected:
            return _terminal(
                "rejected",
                [f"{i.code}:{i.message}" for i in report.issues],
                pinned, 0,
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
            pinned, 0,
        )
    try:
        plan = compiler_module.compile(
            draft, resolution, pinned, sources, contracts.snapshot,
            contracts.graph, principal, scope,
        )
    except compiler_module.CompilerFailure as exc:
        return _terminal("rejected", [f"COMPILER_FAILURE:{exc}"], pinned, 0)

    return {
        "schemaVersion": 1,
        "status": "planned",
        "plan": {key: value for key, value in plan.items() if key != "goalSpec"},
        "goalSpec": plan["goalSpec"],
        "releaseIds": {
            "semanticSnapshotId": pinned.package.semantic_snapshot_id,
            "registrySnapshotId": pinned.package.registry_snapshot_id,
        },
        "writeGatewayCalls": 0,
        "notRun": list(NOT_RUN),
        "reasons": [],
    }
