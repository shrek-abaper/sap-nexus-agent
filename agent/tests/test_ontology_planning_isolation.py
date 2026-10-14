"""Guardrails: new package must reuse only public stable surfaces."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.compiler import compile, goal_spec_for
from sap_nexus_agent.ontology_planning.release import pin_release
from sap_nexus_agent.ontology_planning.resolver import resolve
from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts
from sap_nexus_agent.ontology_planning.contracts import (
    AnalysisNodeDraft,
    ObjectSelector,
    RequestedConclusion,
    RequestedFact,
    SemanticGoalDraft,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "agent/sap_nexus_agent/ontology_planning"

FORBIDDEN_IMPORTS = {
    "sap_nexus_agent.planner.plan_compiler",
    "sap_nexus_agent.planner.plan_compiler_v2",
}
FORBIDDEN_SYMBOLS = {
    "_build_node_v2",
    "_partition_nodes",
    "_project_node_governance",
    "_compute_gaps",
}


def test_no_private_compiler_reuse():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = ".".join(node.module.split(".")[:4])
                full = node.module
                if full.startswith("sap_nexus_agent.planner.plan_compiler"):
                    offenders.append((path.name, node.module))
                for alias in node.names:
                    if alias.name in FORBIDDEN_SYMBOLS:
                        offenders.append((path.name, alias.name))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORTS:
                        offenders.append((path.name, alias.name))
    assert offenders == []


def test_compiled_plans_pass_v2_validator():
    pinned = pin_release(REPO_ROOT)
    sources = load_semantic_sources(REPO_ROOT)
    contracts = build_semantic_contracts(sources)
    draft = SemanticGoalDraft(
        1,
        (
            RequestedFact("sapnexus:InventoryAvailabilityFact", ("availableQuantity",),
                          (ObjectSelector("sapnexus:Material", "material", "DEMOA2"),
                           ObjectSelector("sapnexus:Plant", "plant", "1000"))),
            RequestedFact("sapnexus:MaterialInfoFact", ("baseUnitOfMeasure",),
                          (ObjectSelector("sapnexus:Material", "material", "DEMOA2"),
                           ObjectSelector("sapnexus:Plant", "plant", "1000"))),
        ),
        (), (), (RequestedConclusion("c1", "x", "e"),), (),
    )
    resolution = resolve(
        draft, pinned, sources, contracts.snapshot, contracts.graph,
        {"principalId": "local-user-0001"},
    )
    plan = compile(draft, resolution, pinned, sources, contracts.snapshot,
                   contracts.graph, {"principalId": "local-user-0001"}, {"plant": "1000"})
    from sap_nexus_agent.semantic_planning.validation_v2 import validate_plan_graph_v2

    report = validate_plan_graph_v2(
        contracts.graph, contracts.snapshot, goal_spec_for(plan), plan["readPlan"]
    )
    assert report.valid, [str(i) for i in report.issues]


def test_no_legacy_sources_changed_since_base():
    base = "be39b54d33e949c7057dab16b69b2969a1ec53d3"
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..HEAD", "--",
         "agent/sap_nexus_agent/semantic_planning",
         "agent/sap_nexus_agent/planner",
         "registry/capabilities.yaml", "ontology/fact-types.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "", result.stdout


def test_no_write_or_java_paths():
    base = "be39b54d33e949c7057dab16b69b2969a1ec53d3"
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..HEAD", "--",
         "agent/sap_nexus_agent/approval.py",
         "services/", "frontend/src/runtime/semantic-tools/"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == ""
