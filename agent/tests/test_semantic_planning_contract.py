from copy import deepcopy
from dataclasses import replace
from datetime import date
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from types import MappingProxyType
import unicodedata
import uuid

import jsonschema
import pytest
import yaml

from sap_nexus_agent.semantic_planning.contracts import ValidationIssue
from sap_nexus_agent.semantic_planning.graph import SemanticGraphCompiler
from sap_nexus_agent.semantic_planning.loader import (
    SourceLoadError,
    load_semantic_sources,
    load_yaml_mapping,
)
from sap_nexus_agent.semantic_planning.snapshot import (
    build_registry_snapshot,
    canonical_json_bytes,
)
from sap_nexus_agent.semantic_planning.validation import (
    build_semantic_contracts,
    validate_goal_spec,
    validate_plan_graph,
)
from scripts.validate_registry_contract import (
    RegistryContract,
    load_registry_contract,
    validate_registry_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_CLI_PATH = REPO_ROOT / "scripts/validate-semantic-planning-contract.py"
# Every relation authored in a fixture here is hand-written by definition, so the
# schema requires both fields (T2 task 3.6). Spread instead of repeated so each
# fixture stays about the rule it exercises.
AUTHORED_RELATION = {
    "origin": "manual",
    "justification": "fixture-authored relation",
}
EXPECTED_EVIDENCE_COMMANDS = [
    '"$PYTHON_BIN" scripts/validate-semantic-planning-contract.py',
    '"$PYTHON_BIN" -m pytest agent/tests',
    '"$PYTHON_BIN" -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml',
    '"$PYTHON_BIN" -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json',
    '"$PYTHON_BIN" -m sap_nexus_agent.eval evals/pr_create_cases.json',
    '"$PYTHON_BIN" -m sap_nexus_agent.eval evals/matcher_cases.yaml',
    '"$PYTHON_BIN" -m sap_nexus_agent.eval evals/dry_run_cases.yaml',
    "openspec validate --all --strict",
]
EXPECTED_EVIDENCE_ACTIVE_LINES = [
    "set -euo pipefail",
    'PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"',
    *EXPECTED_EVIDENCE_COMMANDS,
]


def _load_semantic_cli_module():
    module_name = f"_semantic_cli_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name, SEMANTIC_CLI_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_sys_path = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_sys_path
    return module


def _strip_shell_inline_comment(line: str) -> str:
    quote = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "#" and (
            index == 0 or line[index - 1] in {" ", "\t"}
        ):
            return line[:index].rstrip(" \t")
    return line.rstrip(" \t")


def _evidence_script_lines(script: str) -> list[str]:
    raw_lines = script.split("\n")
    lines = []
    for index, raw_line in enumerate(raw_lines):
        line = raw_line
        if index < len(raw_lines) - 1 and line.endswith("\r"):
            line = line[:-1]
        assert "\r" not in line
        assert all(
            character in {" ", "\t"}
            or unicodedata.category(character)[0] not in {"C", "Z"}
            for character in line
        )
        lines.append(line)
    return lines


def _assert_evidence_script_contract(script: str) -> None:
    active_lines = [
        normalized
        for line in _evidence_script_lines(script)
        if (normalized := _strip_shell_inline_comment(line).strip(" \t"))
    ]

    assert active_lines == EXPECTED_EVIDENCE_ACTIVE_LINES


def _load_evidence_script(path: Path | None = None) -> str:
    evidence_path = path or REPO_ROOT / "scripts/verify-agent-callplan-evidence.sh"
    return evidence_path.read_bytes().decode("utf-8")


def _load_semantic_schema(name: str) -> dict:
    return json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _valid_build():
    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))
    assert result.graph is not None and result.snapshot is not None
    return result


def _load_fixture(name: str) -> dict:
    path = REPO_ROOT / "agent/tests/fixtures/semantic_planning" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _goal(**overrides):
    goal = _load_fixture("goal-material-supply.yaml")
    goal.update(overrides)
    return goal


def _valid_plan_inputs():
    build = _valid_build()
    goal = _load_fixture("goal-material-supply.yaml")
    plan = _load_fixture("plan-material-supply.yaml")
    plan["snapshotId"] = build.snapshot.snapshot_id
    return build, goal, plan


def _fact_plan_inputs(*, with_dependency=False, same_fact_inputs=1):
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)
    consumer = deepcopy(capabilities["capabilities"][1])
    consumer["capabilityId"] = "MM.Supply.Summarize"
    consumer["name"] = "Supply Summary"
    consumer["ontologyIri"] = "sapnexus:MM_Supply_Summarize"
    consumer["semanticType"] = "sapnexus:SupplySummaryReadFunction"
    if with_dependency:
        # An authored dependency is only legitimate for a pair the deriver
        # cannot compute (T2 task 3.6.2). Cloning the producer makes
        # sapnexus:InventoryAvailabilityFact ambiguous, so the deriver refuses
        # to pick one and emits no edge -- leaving the ordering to be asserted
        # by hand. The plan names its producer node explicitly, so plan shape
        # is unchanged.
        alternate = deepcopy(
            next(
                capability
                for capability in capabilities["capabilities"]
                if capability["capabilityId"] == "MM.Inventory.GetAvailability"
            )
        )
        alternate["capabilityId"] = "Test.Inventory.GetAvailabilityAlternate"
        alternate["name"] = "Alternate Availability"
        alternate["ontologyIri"] = "sapnexus:Test_Inventory_GetAvailabilityAlternate"
        capabilities["capabilities"].append(alternate)
    consumer["inputs"] = [
        {
            "name": f"availability{index}",
            "semanticType": "sapnexus:AvailableQuantity",
            "bindingKind": "fact",
            "satisfiableByFactType": (
                "sapnexus:InventoryAvailabilityFact"
            ),
            "required": True,
            "type": "number",
            "sapParameter": f"AVAILABILITY_{index}",
        }
        for index in range(same_fact_inputs)
    ]
    capabilities["capabilities"].append(consumer)

    relations = _mutable_document(sources.relations)
    if with_dependency:
        relations["relations"] = [
            {
                "relationId": "relation.supply-summary-needs-inventory",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": "MM.Supply.Summarize",
                "dependsOnCapabilityId": "MM.Inventory.GetAvailability",
            }
        ]

    isolated_sources = replace(
        sources,
        capabilities=capabilities,
        relations=relations,
    )
    build = build_semantic_contracts(isolated_sources)
    assert build.graph is not None and build.snapshot is not None
    goal = _goal(
        goalId="goal.supply-summary",
        desiredFactTypes=["sapnexus:PurchaseOrderSupplyFact"],
    )
    plan = _load_fixture("plan-material-supply.yaml")
    plan.update(
        planId="plan.supply-summary",
        goalId=goal["goalId"],
        snapshotId=build.snapshot.snapshot_id,
    )
    plan["nodes"][1]["capabilityId"] = "MM.Supply.Summarize"
    plan["nodes"][1]["parameterBindings"] = [
        {
            "parameterName": f"availability{index}",
            "source": {
                "kind": "factField",
                "producerNodeId": "inventory",
                "factTypeId": "sapnexus:InventoryAvailabilityFact",
                "field": "availableQuantity",
            },
        }
        for index in range(same_fact_inputs)
    ]
    plan["edges"] = [
        {
            "edgeId": "edge.inventory-to-summary-data",
            "kind": "data",
            "fromNodeId": "inventory",
            "toNodeId": "purchaseOrders",
            "factTypeId": "sapnexus:InventoryAvailabilityFact",
        }
    ]
    if with_dependency:
        plan["edges"].append(
            {
                "edgeId": "edge.inventory-before-summary",
                "kind": "dependency",
                "fromNodeId": "inventory",
                "toNodeId": "purchaseOrders",
            }
        )
    plan["goalOutputs"] = [
        {
            "factTypeId": "sapnexus:PurchaseOrderSupplyFact",
            "producerNodeId": "purchaseOrders",
        }
    ]
    return build, goal, plan


def _plan_issue_tuples(report):
    return tuple(
        (issue.path, issue.code, issue.message) for issue in report.issues
    )


def _assert_plan_report(report, expected_issues):
    assert report.valid is (not expected_issues)
    assert _plan_issue_tuples(report) == expected_issues


class _GraphAccessForbidden:
    def __getattribute__(self, name):
        raise AssertionError(f"shape-invalid GoalSpec accessed graph.{name}")


class _PlanPrerequisiteAccessForbidden:
    def __getattribute__(self, name):
        raise AssertionError(f"shape-invalid PlanGraph accessed prerequisite.{name}")


def test_material_supply_plan_fixture_is_valid_and_has_no_edges():
    build, goal, plan = _valid_plan_inputs()
    jsonschema.validate(plan, _load_semantic_schema("plan-graph.schema.json"))

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    assert report.valid is True
    assert report.issues == ()
    assert plan["edges"] == []


@pytest.mark.parametrize(
    ("mutate", "expected_issues"),
    [
        (
            lambda plan: plan.update(snapshotId="sha256:" + "0" * 64),
            ((
                "/snapshotId",
                "SNAPSHOT_MISMATCH",
                "plan snapshotId does not match RegistrySnapshot",
            ),),
        ),
        (
            lambda plan: plan["nodes"][0].update(
                capabilityId="MM.Unknown.Read"
            ),
            (
                (
                    "/goalOutputs/0/producerNodeId",
                    "GOAL_OUTPUT_UNSATISFIED",
                    "producer node does not project the desired Fact Type",
                ),
                (
                    "/nodes/0/capabilityId",
                    "UNKNOWN_CAPABILITY",
                    "capability is not registered: MM.Unknown.Read",
                ),
                (
                    "/topologicalOrder",
                    "PLAN_PROJECTION_MISMATCH",
                    "topologicalOrder must cover every valid plan node exactly once",
                ),
            ),
        ),
        (
            lambda plan: plan["nodes"].append(deepcopy(plan["nodes"][0])),
            ((
                "/nodes/2/nodeId",
                "DUPLICATE_ID",
                "duplicate nodeId: inventory",
            ),),
        ),
        (
            lambda plan: plan["nodes"][0]["governance"].update(
                sideEffect="sap_write"
            ),
            ((
                "/nodes/0/governance",
                "PLAN_PROJECTION_MISMATCH",
                "governance does not match Registry projection",
            ),),
        ),
        (
            lambda plan: plan["nodes"][0]["parameterBindings"].pop(0),
            ((
                "/nodes/0/parameterBindings",
                "PARAMETER_SOURCE_MISSING",
                "required parameter has no source: material",
            ),),
        ),
        (
            lambda plan: plan["nodes"][0]["parameterBindings"].append(
                deepcopy(plan["nodes"][0]["parameterBindings"][0])
            ),
            ((
                "/nodes/0/parameterBindings/2/parameterName",
                "PARAMETER_SOURCE_DUPLICATE",
                "parameter has multiple sources: material",
            ),),
        ),
        (
            lambda plan: plan["goalOutputs"].pop(),
            ((
                "/goalOutputs",
                "GOAL_OUTPUT_UNSATISFIED",
                "desired Fact Type requires exactly one producer: sapnexus:PurchaseOrderSupplyFact",
            ),),
        ),
        (
            lambda plan: plan.update(bindingId="caller.supplied.binding"),
            ((
                "/bindingId",
                "SCHEMA_INVALID",
                "unexpected property: bindingId",
            ),),
        ),
    ],
    ids=[
        "snapshot",
        "capability",
        "duplicate-node",
        "registry-projection",
        "missing-required-source",
        "duplicate-source",
        "goal-output",
        "technical-binding",
    ],
)
def test_plan_fail_closed_matrix(mutate, expected_issues):
    build, goal, plan = _valid_plan_inputs()
    mutate(plan)

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(report, expected_issues)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("goalId", "goal.other", "plan goalId does not match GoalSpec"),
        (
            "executionMode",
            "PLAN_ONLY",
            "plan executionMode does not match GoalSpec",
        ),
    ],
)
def test_plan_identity_must_match_goal(field, value, message):
    build, goal, plan = _valid_plan_inputs()
    plan[field] = value

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((f"/{field}", "PLAN_PROJECTION_MISMATCH", message),),
    )


@pytest.mark.parametrize(
    ("mutate", "expected_issues"),
    [
        (
            lambda plan: plan.update(rfcName="RFC_CALL"),
            (("/rfcName", "SCHEMA_INVALID", "unexpected property: rfcName"),),
        ),
        (
            lambda plan: plan["nodes"][0].update(
                executor={"type": "JCO_RFC"}
            ),
            ((
                "/nodes/0/executor",
                "SCHEMA_INVALID",
                "unexpected property: executor",
            ),),
        ),
        (
            lambda plan: plan["nodes"][0]["parameterBindings"][0][
                "source"
            ].update(url="https://sap.invalid"),
            (
                (
                    "/nodes/0/parameterBindings/0/source/constraintName",
                    "SCHEMA_INVALID",
                    "unexpected property: constraintName",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/factTypeId",
                    "SCHEMA_INVALID",
                    "factTypeId is required",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/field",
                    "SCHEMA_INVALID",
                    "field is required",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/kind",
                    "SCHEMA_INVALID",
                    "'factField' was expected",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/kind",
                    "SCHEMA_INVALID",
                    "'literal' was expected",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/producerNodeId",
                    "SCHEMA_INVALID",
                    "producerNodeId is required",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/semanticType",
                    "SCHEMA_INVALID",
                    "semanticType is required",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/url",
                    "SCHEMA_INVALID",
                    "unexpected property: url",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/value",
                    "SCHEMA_INVALID",
                    "value is required",
                ),
            ),
        ),
        (
            lambda plan: plan["nodes"][0]["governance"].update(
                credentials="secret"
            ),
            ((
                "/nodes/0/governance/credentials",
                "SCHEMA_INVALID",
                "unexpected property: credentials",
            ),),
        ),
        (
            lambda plan: plan["nodes"][0].update(
                headers={"Authorization": "secret"}
            ),
            ((
                "/nodes/0/headers",
                "SCHEMA_INVALID",
                "unexpected property: headers",
            ),),
        ),
        (
            lambda plan: plan["goalOutputs"][0].update(
                outputMapping={"value": "RFC.VALUE"}
            ),
            ((
                "/goalOutputs/0/outputMapping",
                "SCHEMA_INVALID",
                "unexpected property: outputMapping",
            ),),
        ),
    ],
    ids=["rfc", "executor", "url", "credentials", "headers", "mapping"],
)
def test_plan_schema_recursively_rejects_technical_fields(
    mutate, expected_issues
):
    build, goal, plan = _valid_plan_inputs()
    mutate(plan)

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(report, expected_issues)


@pytest.mark.parametrize(
    ("mutation", "expected_issues"),
    [
        ("version", (("/planGraphVersion", "SCHEMA_INVALID", "1 was expected"),)),
        ("required-root", (("/planId", "SCHEMA_INVALID", "planId is required"),)),
        (
            "snapshot-format",
            ((
                "/snapshotId",
                "SCHEMA_INVALID",
                "'sha256:invalid' does not match '^sha256:[0-9a-f]{64}$'",
            ),),
        ),
        ("empty-nodes", (("/nodes", "SCHEMA_INVALID", "[] should be non-empty"),)),
        (
            "node-required",
            ((
                "/nodes/0/capabilityId",
                "SCHEMA_INVALID",
                "capabilityId is required",
            ),),
        ),
        (
            "binding-required",
            ((
                "/nodes/0/parameterBindings/0/source",
                "SCHEMA_INVALID",
                "source is required",
            ),),
        ),
        (
            "source-union-exclusive",
            (
                (
                    "/nodes/0/parameterBindings/0/source/constraintName",
                    "SCHEMA_INVALID",
                    "unexpected property: constraintName",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/factTypeId",
                    "SCHEMA_INVALID",
                    "factTypeId is required",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/field",
                    "SCHEMA_INVALID",
                    "field is required",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/kind",
                    "SCHEMA_INVALID",
                    "'factField' was expected",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/kind",
                    "SCHEMA_INVALID",
                    "'literal' was expected",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/producerNodeId",
                    "SCHEMA_INVALID",
                    "producerNodeId is required",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/semanticType",
                    "SCHEMA_INVALID",
                    "unexpected property: semanticType",
                ),
                (
                    "/nodes/0/parameterBindings/0/source/value",
                    "SCHEMA_INVALID",
                    "unexpected property: value",
                ),
            ),
        ),
        (
            "empty-projection",
            ((
                "/nodes/0/producesFactTypes",
                "SCHEMA_INVALID",
                "[] should be non-empty",
            ),),
        ),
        (
            "governance-required",
            ((
                "/nodes/0/governance/approvalPolicy",
                "SCHEMA_INVALID",
                "approvalPolicy is required",
            ),),
        ),
        (
            "edge-union-required",
            (
                ("/edges/0/factTypeId", "SCHEMA_INVALID", "factTypeId is required"),
                ("/edges/0/kind", "SCHEMA_INVALID", "'dependency' was expected"),
            ),
        ),
        (
            "edge-union-exclusive",
            (
                (
                    "/edges/0/factTypeId",
                    "SCHEMA_INVALID",
                    "unexpected property: factTypeId",
                ),
                ("/edges/0/kind", "SCHEMA_INVALID", "'data' was expected"),
            ),
        ),
        (
            "empty-order",
            (("/topologicalOrder", "SCHEMA_INVALID", "[] should be non-empty"),),
        ),
        (
            "empty-outputs",
            (("/goalOutputs", "SCHEMA_INVALID", "[] should be non-empty"),),
        ),
        (
            "output-required",
            ((
                "/goalOutputs/0/producerNodeId",
                "SCHEMA_INVALID",
                "producerNodeId is required",
            ),),
        ),
    ],
)
def test_complete_plan_shape_matrix_stops_before_semantic_traversal(
    mutation, expected_issues
):
    _, _, plan = _valid_plan_inputs()
    if mutation == "version":
        plan["planGraphVersion"] = 2
    elif mutation == "required-root":
        del plan["planId"]
    elif mutation == "snapshot-format":
        plan["snapshotId"] = "sha256:invalid"
    elif mutation == "empty-nodes":
        plan["nodes"] = []
    elif mutation == "node-required":
        del plan["nodes"][0]["capabilityId"]
    elif mutation == "binding-required":
        del plan["nodes"][0]["parameterBindings"][0]["source"]
    elif mutation == "source-union-exclusive":
        plan["nodes"][0]["parameterBindings"][0]["source"].update(
            semanticType="sapnexus:MaterialNumber",
            value="MAT-1",
        )
    elif mutation == "empty-projection":
        plan["nodes"][0]["producesFactTypes"] = []
    elif mutation == "governance-required":
        del plan["nodes"][0]["governance"]["approvalPolicy"]
    elif mutation == "edge-union-required":
        plan["edges"] = [
            {
                "edgeId": "edge.incomplete",
                "kind": "data",
                "fromNodeId": "inventory",
                "toNodeId": "purchaseOrders",
            }
        ]
    elif mutation == "edge-union-exclusive":
        plan["edges"] = [
            {
                "edgeId": "edge.mixed",
                "kind": "dependency",
                "fromNodeId": "inventory",
                "toNodeId": "purchaseOrders",
                "factTypeId": "sapnexus:InventoryAvailabilityFact",
            }
        ]
    elif mutation == "empty-order":
        plan["topologicalOrder"] = []
    elif mutation == "empty-outputs":
        plan["goalOutputs"] = []
    elif mutation == "output-required":
        del plan["goalOutputs"][0]["producerNodeId"]
    else:
        raise AssertionError(f"unsupported mutation: {mutation}")

    forbidden = _PlanPrerequisiteAccessForbidden()
    report = validate_plan_graph(forbidden, forbidden, forbidden, plan)

    _assert_plan_report(report, expected_issues)


def test_goal_constraint_and_literal_sources_preserve_semantic_provenance():
    build, goal, plan = _valid_plan_inputs()
    plan["nodes"][0]["parameterBindings"][0]["source"] = {
        "kind": "literal",
        "semanticType": "sapnexus:MaterialNumber",
        "value": "MAT-1",
    }

    valid = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    assert valid.valid is True
    mismatched = deepcopy(plan)
    mismatched["nodes"][0]["parameterBindings"][0]["source"][
        "semanticType"
    ] = "sapnexus:Plant"

    invalid = validate_plan_graph(
        build.graph, build.snapshot, goal, mismatched
    )

    _assert_plan_report(
        invalid,
        ((
            "/nodes/0/parameterBindings/0/source/semanticType",
            "PARAMETER_SOURCE_MISSING",
            "literal cannot satisfy parameter semantic type",
        ),),
    )


def test_goal_constraint_source_must_exist_with_matching_semantic_type():
    build, goal, plan = _valid_plan_inputs()
    goal["constraints"][0]["semanticType"] = "sapnexus:Plant"

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((
            "/nodes/0/parameterBindings/0/source/constraintName",
            "PARAMETER_SOURCE_MISSING",
            "goal constraint cannot satisfy parameter semantic type",
        ), (
            "/nodes/1/parameterBindings/0/source/constraintName",
            "PARAMETER_SOURCE_MISSING",
            "goal constraint cannot satisfy parameter semantic type",
        )),
    )


def test_fact_field_and_data_edge_match_exactly():
    build, goal, plan = _fact_plan_inputs()

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    assert report.valid is True
    assert report.issues == ()


def test_two_same_fact_bindings_share_one_semantic_data_edge():
    build, goal, plan = _fact_plan_inputs(same_fact_inputs=2)

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    assert report.valid is True
    assert report.issues == ()


def test_duplicate_semantic_data_edge_is_rejected_at_second_edge():
    build, goal, plan = _fact_plan_inputs(same_fact_inputs=2)
    duplicate = deepcopy(plan["edges"][0])
    duplicate["edgeId"] = "edge.inventory-to-summary-data-duplicate"
    plan["edges"].append(duplicate)

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    assert report.valid is False
    assert _plan_issue_tuples(report) == (
        (
            "/edges/1",
            "EDGE_INCONSISTENT",
            "duplicate semantic data edge",
        ),
    )


def test_missing_data_edge_is_inconsistent_at_fact_source():
    build, goal, plan = _fact_plan_inputs()
    plan["edges"] = []

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((
            "/nodes/1/parameterBindings/0/source",
            "EDGE_INCONSISTENT",
            "factField source must have exactly one matching data edge",
        ),),
    )


def test_fact_field_requires_matching_producer_fact_and_output_field():
    build, goal, plan = _fact_plan_inputs()
    source = plan["nodes"][1]["parameterBindings"][0]["source"]
    source["factTypeId"] = "sapnexus:PurchaseOrderSupplyFact"
    plan["edges"][0]["factTypeId"] = source["factTypeId"]

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((
            "/nodes/1/parameterBindings/0/source/factTypeId",
            "FACT_TYPE_MISMATCH",
            "fact source cannot satisfy parameter Fact Type",
        ),),
    )

    wrong_field = deepcopy(plan)
    source = wrong_field["nodes"][1]["parameterBindings"][0]["source"]
    source["factTypeId"] = "sapnexus:InventoryAvailabilityFact"
    source["field"] = "notPublished"
    wrong_field["edges"][0]["factTypeId"] = source["factTypeId"]

    field_report = validate_plan_graph(
        build.graph, build.snapshot, goal, wrong_field
    )

    _assert_plan_report(
        field_report,
        ((
            "/nodes/1/parameterBindings/0/source/field",
            "FACT_TYPE_MISMATCH",
            "field is not published for the declared producer Fact Type",
        ),),
    )


def test_fact_field_cannot_supply_identifier_input():
    build, goal, plan = _valid_plan_inputs()
    plan["nodes"][0]["parameterBindings"][0]["source"] = {
        "kind": "factField",
        "producerNodeId": "inventory",
        "factTypeId": "sapnexus:InventoryAvailabilityFact",
        "field": "availableQuantity",
    }

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        (
            (
                "/nodes/0/parameterBindings/0/source",
                "EDGE_INCONSISTENT",
                "factField source must have exactly one matching data edge",
            ),
            (
                "/nodes/0/parameterBindings/0/source/factTypeId",
                "FACT_TYPE_MISMATCH",
                "fact source cannot satisfy parameter Fact Type",
            ),
        ),
    )


def test_extra_data_edge_without_fact_source_is_inconsistent():
    build, goal, plan = _valid_plan_inputs()
    plan["edges"] = [
        {
            "edgeId": "edge.unbacked-data",
            "kind": "data",
            "fromNodeId": "inventory",
            "toNodeId": "purchaseOrders",
            "factTypeId": "sapnexus:InventoryAvailabilityFact",
        }
    ]

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((
            "/edges/0",
            "EDGE_INCONSISTENT",
            "data edge must have at least one matching factField source",
        ),),
    )


def test_authored_dependency_uses_prerequisite_to_dependent_direction():
    build, goal, plan = _fact_plan_inputs(with_dependency=True)

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    assert report.valid is True
    assert report.issues == ()


def test_authored_dependency_rejects_absent_prerequisite_node():
    build, goal, plan = _fact_plan_inputs(with_dependency=True)
    del plan["nodes"][0]
    plan["edges"] = []
    plan["topologicalOrder"] = ["purchaseOrders"]

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        (
            (
                "/edges",
                "EDGE_INCONSISTENT",
                "authored dependency prerequisite is absent: MM.Inventory.GetAvailability",
            ),
            (
                "/nodes/0/parameterBindings/0/source",
                "EDGE_INCONSISTENT",
                "factField source must have exactly one matching data edge",
            ),
            (
                "/nodes/0/parameterBindings/0/source/producerNodeId",
                "FACT_TYPE_MISMATCH",
                "fact producer node is not valid",
            ),
        ),
    )


def test_reversed_dependency_edge_is_inconsistent():
    build, goal, plan = _fact_plan_inputs(with_dependency=True)
    edge = plan["edges"][1]
    edge["fromNodeId"], edge["toNodeId"] = (
        edge["toNodeId"],
        edge["fromNodeId"],
    )

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        (
            (
                "/edges",
                "EDGE_INCONSISTENT",
                "authored dependency requires one prerequisite-to-dependent edge",
            ),
            (
                "/edges/1",
                "EDGE_INCONSISTENT",
                "dependency edge does not match authored dependsOn relation",
            ),
            (
                "/edges/1/toNodeId",
                "DEPENDENCY_CYCLE",
                "plan edge cycle detected: inventory -> purchaseOrders -> inventory",
            ),
            (
                "/topologicalOrder",
                "EDGE_INCONSISTENT",
                "topologicalOrder violates a plan edge direction",
            ),
        ),
    )


def test_plan_edge_cycle_is_reported_at_cycle_closing_endpoint():
    build, goal, plan = _fact_plan_inputs(with_dependency=True)
    plan["edges"].append(
        {
            "edgeId": "edge.summary-before-inventory",
            "kind": "dependency",
            "fromNodeId": "purchaseOrders",
            "toNodeId": "inventory",
        }
    )

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        (
            (
                "/edges/2",
                "EDGE_INCONSISTENT",
                "dependency edge does not match authored dependsOn relation",
            ),
            (
                "/edges/2/toNodeId",
                "DEPENDENCY_CYCLE",
                "plan edge cycle detected: inventory -> purchaseOrders -> inventory",
            ),
            (
                "/topologicalOrder",
                "EDGE_INCONSISTENT",
                "topologicalOrder violates a plan edge direction",
            ),
        ),
    )


def test_topological_order_must_follow_all_authored_edges():
    build, goal, plan = _fact_plan_inputs()
    plan["topologicalOrder"] = ["purchaseOrders", "inventory"]

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((
            "/topologicalOrder",
            "EDGE_INCONSISTENT",
            "topologicalOrder violates a plan edge direction",
        ),),
    )


def test_read_only_plan_rejects_non_read_only_registry_governance():
    build, goal, plan = _valid_plan_inputs()
    capabilities = dict(build.graph.capabilities)
    inventory = dict(capabilities["MM.Inventory.GetAvailability"])
    inventory["governance"] = MappingProxyType(
        {
            **dict(inventory["governance"]),
            "sideEffect": "read",
        }
    )
    capabilities["MM.Inventory.GetAvailability"] = MappingProxyType(inventory)
    graph = replace(
        build.graph,
        capabilities=MappingProxyType(capabilities),
    )
    plan["nodes"][0]["governance"]["sideEffect"] = "read"

    report = validate_plan_graph(graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((
            "/nodes/0/governance",
            "GOVERNANCE_VIOLATION",
            "READ_ONLY plan contains a non-read-only capability",
        ),),
    )


def test_goal_output_producer_must_project_the_desired_fact():
    build, goal, plan = _valid_plan_inputs()
    plan["goalOutputs"][0]["producerNodeId"] = "purchaseOrders"

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        ((
            "/goalOutputs/0/producerNodeId",
            "GOAL_OUTPUT_UNSATISFIED",
            "producer node does not project the desired Fact Type",
        ),),
    )


@pytest.mark.parametrize(
    ("case", "expected_issues"),
    [
        (
            "duplicate-edge-id",
            ((
                "/edges/1/edgeId",
                "DUPLICATE_ID",
                "duplicate edgeId: edge.inventory-to-summary-data",
            ),),
        ),
        (
            "duplicate-semantic-dependency",
            (
                (
                    "/edges",
                    "EDGE_INCONSISTENT",
                    "authored dependency requires one prerequisite-to-dependent edge",
                ),
                (
                    "/edges/1",
                    "EDGE_INCONSISTENT",
                    "dependency edge does not match authored dependsOn relation",
                ),
                (
                    "/edges/2",
                    "EDGE_INCONSISTENT",
                    "dependency edge does not match authored dependsOn relation",
                ),
            ),
        ),
        (
            "unknown-endpoint",
            (
                (
                    "/edges/0",
                    "EDGE_INCONSISTENT",
                    "dependency edge does not match authored dependsOn relation",
                ),
                (
                    "/topologicalOrder",
                    "EDGE_INCONSISTENT",
                    "topologicalOrder violates a plan edge direction",
                ),
            ),
        ),
        (
            "extra-dependency",
            ((
                "/edges/0",
                "EDGE_INCONSISTENT",
                "dependency edge does not match authored dependsOn relation",
            ),),
        ),
        (
            "kind-confusion",
            (
                (
                    "/edges/0",
                    "EDGE_INCONSISTENT",
                    "dependency edge does not match authored dependsOn relation",
                ),
                (
                    "/nodes/1/parameterBindings/0/source",
                    "EDGE_INCONSISTENT",
                    "factField source must have exactly one matching data edge",
                ),
            ),
        ),
        (
            "missing-authored-dependency",
            ((
                "/edges",
                "EDGE_INCONSISTENT",
                "authored dependency requires one prerequisite-to-dependent edge",
            ),),
        ),
    ],
)
def test_plan_edge_negative_matrix_has_exact_reports(case, expected_issues):
    with_dependency = case in {
        "duplicate-semantic-dependency",
        "missing-authored-dependency",
    }
    if case in {"duplicate-edge-id", "kind-confusion"} or with_dependency:
        build, goal, plan = _fact_plan_inputs(with_dependency=with_dependency)
    else:
        build, goal, plan = _valid_plan_inputs()

    if case == "duplicate-edge-id":
        plan["edges"].append(deepcopy(plan["edges"][0]))
    elif case == "duplicate-semantic-dependency":
        duplicate = deepcopy(plan["edges"][1])
        duplicate["edgeId"] = "edge.duplicate-dependency"
        plan["edges"].append(duplicate)
    elif case == "unknown-endpoint":
        plan["edges"] = [{
            "edgeId": "edge.unknown-dependency",
            "kind": "dependency",
            "fromNodeId": "unknown",
            "toNodeId": "purchaseOrders",
        }]
    elif case == "extra-dependency":
        plan["edges"] = [{
            "edgeId": "edge.extra-dependency",
            "kind": "dependency",
            "fromNodeId": "inventory",
            "toNodeId": "purchaseOrders",
        }]
    elif case == "kind-confusion":
        plan["edges"] = [{
            "edgeId": "edge.wrong-kind",
            "kind": "dependency",
            "fromNodeId": "inventory",
            "toNodeId": "purchaseOrders",
        }]
    elif case == "missing-authored-dependency":
        plan["edges"].pop()
    else:
        raise AssertionError(f"unsupported edge case: {case}")

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(report, expected_issues)


def test_optional_parameter_may_be_omitted_or_present_once():
    build, goal, omitted = _valid_plan_inputs()
    present = deepcopy(omitted)
    present["nodes"][0]["parameterBindings"].append({
        "parameterName": "unit",
        "source": {
            "kind": "literal",
            "semanticType": "sapnexus:UnitOfMeasure",
            "value": "EA",
        },
    })

    _assert_plan_report(
        validate_plan_graph(build.graph, build.snapshot, goal, omitted), ()
    )
    _assert_plan_report(
        validate_plan_graph(build.graph, build.snapshot, goal, present), ()
    )


@pytest.mark.parametrize(
    ("case", "expected_issues"),
    [
        (
            "unknown-parameter",
            ((
                "/nodes/0/parameterBindings/2/parameterName",
                "PLAN_PROJECTION_MISMATCH",
                "parameter is not registered: unknown",
            ),),
        ),
        (
            "duplicate-optional",
            ((
                "/nodes/0/parameterBindings/3/parameterName",
                "PARAMETER_SOURCE_DUPLICATE",
                "parameter has multiple sources: unit",
            ),),
        ),
        (
            "missing-goal-constraint",
            ((
                "/nodes/0/parameterBindings/0/source/constraintName",
                "PARAMETER_SOURCE_MISSING",
                "goal constraint cannot satisfy parameter semantic type",
            ),),
        ),
        (
            "literal-to-fact",
            (
                (
                    "/edges/0",
                    "EDGE_INCONSISTENT",
                    "data edge must have at least one matching factField source",
                ),
                (
                    "/nodes/1/parameterBindings/0/source/semanticType",
                    "PARAMETER_SOURCE_MISSING",
                    "literal cannot satisfy parameter semantic type",
                ),
            ),
        ),
        (
            "unknown-fact-producer",
            (
                (
                    "/nodes/1/parameterBindings/0/source",
                    "EDGE_INCONSISTENT",
                    "factField source must have exactly one matching data edge",
                ),
                (
                    "/nodes/1/parameterBindings/0/source/producerNodeId",
                    "FACT_TYPE_MISMATCH",
                    "fact producer node is not valid",
                ),
            ),
        ),
    ],
)
def test_parameter_source_negative_matrix_has_exact_reports(case, expected_issues):
    if case in {"literal-to-fact", "unknown-fact-producer"}:
        build, goal, plan = _fact_plan_inputs()
    else:
        build, goal, plan = _valid_plan_inputs()

    if case == "unknown-parameter":
        plan["nodes"][0]["parameterBindings"].append({
            "parameterName": "unknown",
            "source": {"kind": "literal", "semanticType": "x", "value": "x"},
        })
    elif case == "duplicate-optional":
        binding = {
            "parameterName": "unit",
            "source": {
                "kind": "literal",
                "semanticType": "sapnexus:UnitOfMeasure",
                "value": "EA",
            },
        }
        plan["nodes"][0]["parameterBindings"].extend(
            [binding, deepcopy(binding)]
        )
    elif case == "missing-goal-constraint":
        plan["nodes"][0]["parameterBindings"][0]["source"][
            "constraintName"
        ] = "absent"
    elif case == "literal-to-fact":
        plan["nodes"][1]["parameterBindings"][0]["source"] = {
            "kind": "literal",
            "semanticType": "sapnexus:AvailableQuantity",
            "value": 1,
        }
    elif case == "unknown-fact-producer":
        plan["nodes"][1]["parameterBindings"][0]["source"][
            "producerNodeId"
        ] = "unknown"
        plan["edges"] = []

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(report, expected_issues)


def test_non_scalar_literal_has_exact_shape_report():
    build, goal, plan = _valid_plan_inputs()
    plan["nodes"][0]["parameterBindings"][0]["source"] = {
        "kind": "literal",
        "semanticType": "sapnexus:MaterialNumber",
        "value": ["not-scalar"],
    }

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    expected_by_suffix = (
        ("constraintName", "constraintName is required"),
        ("factTypeId", "factTypeId is required"),
        ("field", "field is required"),
        ("kind", "'factField' was expected"),
        ("kind", "'goalConstraint' was expected"),
        ("producerNodeId", "producerNodeId is required"),
        ("semanticType", "unexpected property: semanticType"),
        ("value", "['not-scalar'] is not of type 'string', 'number', 'integer', 'boolean'"),
        ("value", "unexpected property: value"),
    )
    base = "/nodes/0/parameterBindings/0/source"
    _assert_plan_report(
        report,
        tuple(
            (f"{base}/{suffix}", "SCHEMA_INVALID", message)
            for suffix, message in expected_by_suffix
        ),
    )


@pytest.mark.parametrize(
    ("order", "expected_issues"),
    [
        (
            ["inventory", "unknown"],
            ((
                "/topologicalOrder",
                "PLAN_PROJECTION_MISMATCH",
                "topologicalOrder must cover every valid plan node exactly once",
            ),),
        ),
        (
            ["inventory", "inventory"],
            ((
                "/topologicalOrder",
                "SCHEMA_INVALID",
                "['inventory', 'inventory'] has non-unique elements",
            ),),
        ),
        (
            ["inventory"],
            ((
                "/topologicalOrder",
                "PLAN_PROJECTION_MISMATCH",
                "topologicalOrder must cover every valid plan node exactly once",
            ),),
        ),
    ],
)
def test_topological_coverage_matrix_has_exact_reports(order, expected_issues):
    build, goal, plan = _valid_plan_inputs()
    plan["topologicalOrder"] = order

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(report, expected_issues)


@pytest.mark.parametrize(
    ("case", "expected_issues"),
    [
        (
            "extra",
            ((
                "/goalOutputs/2/factTypeId",
                "GOAL_OUTPUT_UNSATISFIED",
                "goal output is not requested by GoalSpec",
            ),),
        ),
        (
            "duplicate",
            ((
                "/goalOutputs",
                "GOAL_OUTPUT_UNSATISFIED",
                "desired Fact Type requires exactly one producer: sapnexus:InventoryAvailabilityFact",
            ),),
        ),
        (
            "unknown-producer",
            ((
                "/goalOutputs/0/producerNodeId",
                "GOAL_OUTPUT_UNSATISFIED",
                "producer node does not project the desired Fact Type",
            ),),
        ),
    ],
)
def test_goal_output_negative_matrix_has_exact_reports(case, expected_issues):
    build, goal, plan = _valid_plan_inputs()
    if case == "extra":
        plan["goalOutputs"].append({
            "factTypeId": "sapnexus:OtherFact",
            "producerNodeId": "inventory",
        })
    elif case == "duplicate":
        plan["goalOutputs"].append({
            "factTypeId": "sapnexus:InventoryAvailabilityFact",
            "producerNodeId": "purchaseOrders",
        })
    else:
        plan["goalOutputs"][0]["producerNodeId"] = "unknown"

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(report, expected_issues)


@pytest.mark.parametrize(
    ("execution_mode", "expected_issues"),
    [
        (
            "READ_ONLY",
            ((
                "/nodes/0/governance",
                "GOVERNANCE_VIOLATION",
                "READ_ONLY plan contains a non-read-only capability",
            ),),
        ),
        ("PLAN_ONLY", ()),
    ],
)
def test_real_registry_action_respects_execution_mode(execution_mode, expected_issues):
    build = _valid_build()
    capability = build.graph.capabilities["MM.PR.CreateDraft"]
    goal = {
        "goalId": "goal.pr-draft",
        "executionMode": execution_mode,
        "desiredFactTypes": ["sapnexus:PurchaseRequisitionCreatedFact"],
    }
    scalar_values = {"quantity": 1}
    plan = {
        "planGraphVersion": 1,
        "planId": "plan.pr-draft",
        "goalId": goal["goalId"],
        "executionMode": execution_mode,
        "snapshotId": build.snapshot.snapshot_id,
        "nodes": [{
            "nodeId": "createDraft",
            "capabilityId": capability["capabilityId"],
            "parameterBindings": [
                {
                    "parameterName": item["name"],
                    "source": {
                        "kind": "literal",
                        "semanticType": item["semanticType"],
                        "value": scalar_values.get(item["name"], "value"),
                    },
                }
                for item in capability["inputs"]
                if item["required"]
            ],
            "producesFactTypes": ["sapnexus:PurchaseRequisitionCreatedFact"],
            "governance": {
                "capabilityKind": capability["kind"],
                "sideEffect": capability["governance"]["sideEffect"],
                "requiresApproval": capability["governance"]["requiresApproval"],
                "approvalPolicy": capability["governance"]["approvalPolicy"],
            },
        }],
        "edges": [],
        "topologicalOrder": ["createDraft"],
        "goalOutputs": [{
            "factTypeId": "sapnexus:PurchaseRequisitionCreatedFact",
            "producerNodeId": "createDraft",
        }],
    }

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(report, expected_issues)


def test_technical_key_case_variant_and_nested_container_fail_at_allowlist_boundary():
    build, goal, plan = _valid_plan_inputs()
    plan["ExEcUtOr"] = {"container": [{"HeAdErS": {"Credential": "x"}}]}

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    _assert_plan_report(
        report,
        (("/ExEcUtOr", "SCHEMA_INVALID", "unexpected property: ExEcUtOr"),),
    )


def test_validation_preserves_authored_plan_and_creates_no_authority_artifact():
    build, goal, plan = _valid_plan_inputs()
    before = deepcopy(plan)

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    assert plan == before
    assert report.__dict__ == {"valid": True, "issues": ()}
    assert not ({"execution", "approval", "artifact"} & set(report.__dict__))


def _recursive_plan():
    _, _, plan = _valid_plan_inputs()
    plan["nodes"][0]["governance"]["executor"] = plan["nodes"][0]
    return plan


@pytest.mark.parametrize(
    ("malformed_plan", "expected_issues"),
    [
        (
            "truthy-scalar",
            (("", "SCHEMA_INVALID", "'truthy-scalar' is not of type 'object'"),),
        ),
        (
            ["truthy-list"],
            (("", "SCHEMA_INVALID", "['truthy-list'] is not of type 'object'"),),
        ),
        (
            {"nodes": "truthy-scalar"},
            (
                ("/edges", "SCHEMA_INVALID", "edges is required"),
                ("/executionMode", "SCHEMA_INVALID", "executionMode is required"),
                ("/goalId", "SCHEMA_INVALID", "goalId is required"),
                ("/goalOutputs", "SCHEMA_INVALID", "goalOutputs is required"),
                ("/nodes", "SCHEMA_INVALID", "'truthy-scalar' is not of type 'array'"),
                ("/planGraphVersion", "SCHEMA_INVALID", "planGraphVersion is required"),
                ("/planId", "SCHEMA_INVALID", "planId is required"),
                ("/snapshotId", "SCHEMA_INVALID", "snapshotId is required"),
                ("/topologicalOrder", "SCHEMA_INVALID", "topologicalOrder is required"),
            ),
        ),
        (
            {"nodes": ["truthy-item"]},
            (
                ("/edges", "SCHEMA_INVALID", "edges is required"),
                ("/executionMode", "SCHEMA_INVALID", "executionMode is required"),
                ("/goalId", "SCHEMA_INVALID", "goalId is required"),
                ("/goalOutputs", "SCHEMA_INVALID", "goalOutputs is required"),
                ("/nodes/0", "SCHEMA_INVALID", "'truthy-item' is not of type 'object'"),
                ("/planGraphVersion", "SCHEMA_INVALID", "planGraphVersion is required"),
                ("/planId", "SCHEMA_INVALID", "planId is required"),
                ("/snapshotId", "SCHEMA_INVALID", "snapshotId is required"),
                ("/topologicalOrder", "SCHEMA_INVALID", "topologicalOrder is required"),
            ),
        ),
        (
            {"edges": {"unsupported"}},
            (
                ("/edges", "SCHEMA_INVALID", "unsupported JSON value: set"),
                ("/executionMode", "SCHEMA_INVALID", "executionMode is required"),
                ("/goalId", "SCHEMA_INVALID", "goalId is required"),
                ("/goalOutputs", "SCHEMA_INVALID", "goalOutputs is required"),
                ("/nodes", "SCHEMA_INVALID", "nodes is required"),
                ("/planGraphVersion", "SCHEMA_INVALID", "planGraphVersion is required"),
                ("/planId", "SCHEMA_INVALID", "planId is required"),
                ("/snapshotId", "SCHEMA_INVALID", "snapshotId is required"),
                ("/topologicalOrder", "SCHEMA_INVALID", "topologicalOrder is required"),
            ),
        ),
        (
            _recursive_plan(),
            (
                (
                    "/nodes/0/governance/executor",
                    "SCHEMA_INVALID",
                    "recursive JSON container",
                ),
                (
                    "/nodes/0/governance/executor",
                    "SCHEMA_INVALID",
                    "unexpected property: executor",
                ),
            ),
        ),
    ],
    ids=[
        "root-scalar",
        "root-list",
        "container",
        "item",
        "unsupported",
        "recursive",
    ],
)
def test_malformed_plan_shapes_are_total_before_semantic_traversal(
    malformed_plan, expected_issues
):
    forbidden = _PlanPrerequisiteAccessForbidden()

    first = validate_plan_graph(forbidden, forbidden, forbidden, malformed_plan)
    second = validate_plan_graph(forbidden, forbidden, forbidden, malformed_plan)

    assert first == second
    _assert_plan_report(first, expected_issues)


def test_deep_invalid_technical_mapping_fails_closed_without_recursion_error():
    forbidden = _PlanPrerequisiteAccessForbidden()
    _, _, plan = _valid_plan_inputs()
    nested = {}
    for _ in range(1100):
        nested = {"executor": nested}
    plan["executor"] = nested

    report = validate_plan_graph(forbidden, forbidden, forbidden, plan)

    _assert_plan_report(
        report,
        (
            ("/executor", "SCHEMA_INVALID", "unexpected property: executor"),
            (
                "/executor" + "/executor" * 63,
                "SCHEMA_INVALID",
                "JSON container nesting exceeds safe depth",
            ),
        ),
    )


def test_long_shape_valid_plan_graph_returns_report_without_recursion_error():
    build, goal, plan = _valid_plan_inputs()
    node_template = plan["nodes"][0]
    plan["nodes"] = []
    for index in range(1050):
        node = deepcopy(node_template)
        node["nodeId"] = f"node-{index:04d}"
        plan["nodes"].append(node)
    plan["edges"] = [
        {
            "edgeId": f"edge-{index:04d}",
            "kind": "dependency",
            "fromNodeId": f"node-{index:04d}",
            "toNodeId": f"node-{index + 1:04d}",
        }
        for index in range(1049)
    ]
    plan["topologicalOrder"] = [
        f"node-{index:04d}" for index in range(1050)
    ]
    plan["goalOutputs"] = [
        {
            "factTypeId": "sapnexus:InventoryAvailabilityFact",
            "producerNodeId": "node-0000",
        }
    ]

    report = validate_plan_graph(build.graph, build.snapshot, goal, plan)

    expected_edges = tuple(
        sorted(
            (
                f"/edges/{index}",
                "EDGE_INCONSISTENT",
                "dependency edge does not match authored dependsOn relation",
            )
            for index in range(1049)
        )
    )
    _assert_plan_report(
        report,
        expected_edges
        + ((
            "/goalOutputs",
            "GOAL_OUTPUT_UNSATISFIED",
            "desired Fact Type requires exactly one producer: sapnexus:PurchaseOrderSupplyFact",
        ),),
    )


def test_material_supply_goal_is_reachable():
    graph = _valid_build().graph
    goal = _load_fixture("goal-material-supply.yaml")
    jsonschema.validate(goal, _load_semantic_schema("goal-spec.schema.json"))

    report = validate_goal_spec(graph, goal)

    assert report.valid is True
    assert report.issues == ()
    assert report.reachable_fact_types == (
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
    )
    assert report.capability_gaps == ()


def test_unknown_fact_is_not_a_capability_gap():
    graph = _valid_build().graph

    report = validate_goal_spec(
        graph,
        _goal(desiredFactTypes=["sapnexus:NotPublished"]),
    )

    assert [item.code for item in report.issues] == ["UNKNOWN_FACT_TYPE"]
    assert report.reachable_fact_types == ()
    assert report.capability_gaps == ()


def test_published_fact_without_active_producer_is_capability_gap():
    graph = _valid_build().graph
    fact_types = dict(graph.fact_types)
    fact_types["sapnexus:PublishedWithoutProducer"] = MappingProxyType(
        {
            "factTypeId": "sapnexus:PublishedWithoutProducer",
            "name": "Published Without Producer",
            "description": "Test-only published fact.",
            "businessObject": "TestObject",
            "predicate": "sapnexus:hasPublishedWithoutProducer",
            "semanticType": "sapnexus:PublishedWithoutProducerValue",
            "keyedBy": ("sapnexus:TestKey",),
        }
    )
    graph = replace(graph, fact_types=MappingProxyType(fact_types))

    report = validate_goal_spec(
        graph,
        _goal(
            goalId="goal.gap",
            goalType="sapnexus:GapGoal",
            executionMode="PLAN_ONLY",
            desiredFactTypes=["sapnexus:PublishedWithoutProducer"],
            constraints=[],
        ),
    )

    assert [item.code for item in report.issues] == ["CAPABILITY_GAP"]
    assert report.reachable_fact_types == ()
    assert report.capability_gaps == ("sapnexus:PublishedWithoutProducer",)


@pytest.mark.parametrize(
    ("overrides", "expected_path"),
    [
        ({"goalSpecVersion": 2}, "/goalSpecVersion"),
        ({"executionMode": "EXECUTE"}, "/executionMode"),
        ({"desiredFactTypes": []}, "/desiredFactTypes"),
        (
            {
                "desiredFactTypes": [
                    "sapnexus:InventoryAvailabilityFact",
                    "sapnexus:InventoryAvailabilityFact",
                ]
            },
            "/desiredFactTypes",
        ),
        (
            {
                "constraints": [
                    {
                        "name": "material",
                        "semanticType": "sapnexus:MaterialNumber",
                        "value": "MAT-1",
                    },
                    {
                        "name": "material",
                        "semanticType": "sapnexus:MaterialNumber",
                        "value": "MAT-2",
                    },
                ]
            },
            "/constraints/1/name",
        ),
        (
            {"constraints": [{"semanticType": "sapnexus:Plant", "value": "5300"}]},
            "/constraints/0/name",
        ),
        (
            {
                "constraints": [
                    {
                        "name": "plant",
                        "semanticType": "sapnexus:Plant",
                        "value": ["5300"],
                    }
                ]
            },
            "/constraints/0/value",
        ),
    ],
    ids=[
        "version",
        "mode",
        "empty-desired",
        "duplicate-desired",
        "duplicate-constraint-name",
        "constraint-required-field",
        "constraint-scalar-value",
    ],
)
def test_goal_shape_rules_fail_closed_before_reachability(
    overrides, expected_path
):
    report = validate_goal_spec(_valid_build().graph, _goal(**overrides))

    assert report.valid is False
    assert {item.code for item in report.issues} == {"SCHEMA_INVALID"}
    assert expected_path in {item.path for item in report.issues}
    assert report.reachable_fact_types == ()
    assert report.capability_gaps == ()


@pytest.mark.parametrize(
    "malformed_goal",
    [
        "truthy-scalar",
        ["truthy-list-item"],
        _goal(desiredFactTypes="truthy-scalar"),
        _goal(desiredFactTypes=[["truthy-item"]]),
        _goal(constraints="truthy-scalar"),
        _goal(constraints=["truthy-item"]),
        _goal(
            constraints=[
                {
                    "name": "plant",
                    "semanticType": "sapnexus:Plant",
                    "value": ["truthy-value"],
                }
            ]
        ),
    ],
    ids=[
        "root-scalar",
        "root-list",
        "desired-scalar",
        "desired-item",
        "constraints-scalar",
        "constraint-item",
        "constraint-value",
    ],
)
def test_malformed_goal_shapes_are_total_and_deterministic(malformed_goal):
    graph = _valid_build().graph

    first = validate_goal_spec(graph, malformed_goal)
    second = validate_goal_spec(graph, malformed_goal)

    assert first == second
    assert first.valid is False
    assert first.issues
    assert {item.code for item in first.issues} == {"SCHEMA_INVALID"}
    assert first.issues == tuple(
        sorted(first.issues, key=lambda item: (item.path, item.code, item.message))
    )
    assert first.reachable_fact_types == ()
    assert first.capability_gaps == ()


def test_goal_findings_dedupe_only_identical_triples():
    goal = _goal()
    goal[1] = "first non-string key"
    goal[2] = "second non-string key"

    report = validate_goal_spec(_GraphAccessForbidden(), goal)

    assert report.issues == (
        ValidationIssue("", "SCHEMA_INVALID", "mapping keys must be strings"),
    )
    assert report.reachable_fact_types == ()
    assert report.capability_gaps == ()


def test_distinct_unsupported_desired_facts_do_not_create_unique_items_error():
    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(desiredFactTypes=[date(2026, 7, 19), {"unsupported"}]),
    )

    assert report.issues == (
        ValidationIssue(
            "/desiredFactTypes/0",
            "SCHEMA_INVALID",
            "unsupported JSON value: date",
        ),
        ValidationIssue(
            "/desiredFactTypes/1",
            "SCHEMA_INVALID",
            "unsupported JSON value: set",
        ),
    )
    assert report.reachable_fact_types == ()
    assert report.capability_gaps == ()


@pytest.mark.parametrize(
    ("unsupported", "type_name"),
    [
        (float("nan"), "float"),
        (date(2026, 7, 19), "date"),
        ({"unsupported"}, "set"),
    ],
    ids=["nan", "date", "set"],
)
def test_unsupported_goal_values_fail_closed_without_graph_access(
    unsupported, type_name
):
    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(desiredFactTypes=[unsupported]),
    )

    assert report.issues == (
        ValidationIssue(
            "/desiredFactTypes/0",
            "SCHEMA_INVALID",
            f"unsupported JSON value: {type_name}",
        ),
    )
    assert report.reachable_fact_types == ()
    assert report.capability_gaps == ()


def test_real_duplicate_desired_fact_keeps_container_schema_error():
    fact_type_id = "sapnexus:InventoryAvailabilityFact"

    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(
            desiredFactTypes=[
                fact_type_id,
                fact_type_id,
                date(2026, 7, 19),
                {"unsupported"},
            ]
        ),
    )

    assert len(report.issues) == 3
    assert {issue.path for issue in report.issues} == {
        "/desiredFactTypes",
        "/desiredFactTypes/2",
        "/desiredFactTypes/3",
    }
    assert {issue.code for issue in report.issues} == {"SCHEMA_INVALID"}


def test_numeric_equivalent_constraints_keep_error_with_synthetic_pair():
    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(
            constraints=[
                {
                    "name": "real",
                    "semanticType": "sapnexus:Number",
                    "value": 1,
                },
                {
                    "name": "real",
                    "semanticType": "sapnexus:Number",
                    "value": 1.0,
                },
                {
                    "name": "converted",
                    "semanticType": "sapnexus:Value",
                    "value": date(2026, 7, 19),
                },
                {
                    "name": "converted",
                    "semanticType": "sapnexus:Value",
                    "value": {"unsupported"},
                },
            ]
        ),
    )

    assert "/constraints" in {issue.path for issue in report.issues}
    assert ValidationIssue(
        "/constraints/2/value",
        "SCHEMA_INVALID",
        "unsupported JSON value: date",
    ) in report.issues
    assert ValidationIssue(
        "/constraints/3/value",
        "SCHEMA_INVALID",
        "unsupported JSON value: set",
    ) in report.issues


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ([0], [-0.0]),
        (
            {"outer": [1, {"zero": 0}]},
            {"outer": [1.0, {"zero": -0.0}]},
        ),
    ],
    ids=["zero-list", "nested-mapping-list"],
)
def test_recursive_numeric_equality_keeps_error_with_synthetic_pair(
    left, right
):
    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(
            desiredFactTypes=[
                left,
                right,
                date(2026, 7, 19),
                {"unsupported"},
            ]
        ),
    )

    assert "/desiredFactTypes" in {issue.path for issue in report.issues}
    assert ValidationIssue(
        "/desiredFactTypes/2",
        "SCHEMA_INVALID",
        "unsupported JSON value: date",
    ) in report.issues
    assert ValidationIssue(
        "/desiredFactTypes/3",
        "SCHEMA_INVALID",
        "unsupported JSON value: set",
    ) in report.issues


def test_boolean_and_number_do_not_form_untouched_duplicate_pair():
    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(
            desiredFactTypes=[
                True,
                1,
                date(2026, 7, 19),
                {"unsupported"},
            ]
        ),
    )

    assert "/desiredFactTypes" not in {issue.path for issue in report.issues}
    assert {issue.path for issue in report.issues} == {
        "/desiredFactTypes/0",
        "/desiredFactTypes/1",
        "/desiredFactTypes/2",
        "/desiredFactTypes/3",
    }


def test_converted_and_untouched_normalized_equal_pair_is_suppressed():
    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(desiredFactTypes=[None, date(2026, 7, 19)]),
    )

    assert "/desiredFactTypes" not in {issue.path for issue in report.issues}
    assert {issue.path for issue in report.issues} == {
        "/desiredFactTypes/0",
        "/desiredFactTypes/1",
    }


def test_goal_findings_keep_independent_same_path_schema_violations():
    report = validate_goal_spec(
        _GraphAccessForbidden(),
        _goal(goalSpecVersion=True),
    )

    same_path = [
        issue for issue in report.issues if issue.path == "/goalSpecVersion"
    ]
    assert len(same_path) == 2
    assert len({issue.message for issue in same_path}) == 2


def _goal_with_recursive_mapping():
    constraint = {
        "name": "material",
        "semanticType": "sapnexus:MaterialNumber",
    }
    constraint["value"] = constraint
    return _goal(constraints=[constraint])


def _goal_with_recursive_list():
    desired_fact_types = []
    desired_fact_types.append(desired_fact_types)
    return _goal(desiredFactTypes=desired_fact_types)


def _goal_with_recursive_yaml_alias():
    return yaml.safe_load(
        """
goalSpecVersion: 1
goalId: goal.recursive-alias
goalType: sapnexus:MaterialSupplySnapshot
executionMode: READ_ONLY
desiredFactTypes:
  - sapnexus:InventoryAvailabilityFact
constraints:
  - &constraint
    name: material
    semanticType: sapnexus:MaterialNumber
    value: *constraint
"""
    )


@pytest.mark.parametrize(
    ("goal_factory", "expected_path"),
    [
        (_goal_with_recursive_mapping, "/constraints/0/value"),
        (_goal_with_recursive_list, "/desiredFactTypes/0"),
        (_goal_with_recursive_yaml_alias, "/constraints/0/value"),
    ],
    ids=["mapping", "list", "yaml-alias"],
)
def test_recursive_goal_containers_fail_closed_at_exact_path(
    goal_factory, expected_path
):
    report = validate_goal_spec(_GraphAccessForbidden(), goal_factory())

    assert ValidationIssue(
        expected_path,
        "SCHEMA_INVALID",
        "recursive JSON container",
    ) in report.issues
    assert report.reachable_fact_types == ()
    assert report.capability_gaps == ()


def test_shared_non_recursive_yaml_alias_is_not_reported_as_cycle():
    goal = yaml.safe_load(
        """
goalSpecVersion: 1
goalId: goal.shared-alias
goalType: sapnexus:MaterialSupplySnapshot
executionMode: READ_ONLY
desiredFactTypes:
  - sapnexus:InventoryAvailabilityFact
constraints:
  - &constraint
    name: material
    semanticType: sapnexus:MaterialNumber
    value: MAT-1
  - *constraint
"""
    )

    report = validate_goal_spec(_GraphAccessForbidden(), goal)

    assert {issue.path for issue in report.issues} == {
        "/constraints",
        "/constraints/1/name",
    }
    assert all(
        issue.message != "recursive JSON container" for issue in report.issues
    )


@pytest.mark.parametrize(
    ("execution_mode", "expected_valid", "expected_code"),
    [
        ("READ_ONLY", False, "GOVERNANCE_VIOLATION"),
        ("PLAN_ONLY", True, None),
    ],
)
def test_action_fact_reachability_respects_execution_mode_governance(
    execution_mode, expected_valid, expected_code
):
    graph = _valid_build().graph
    action_id = "MM.PR.CreateDraft"
    action_before = graph.capabilities[action_id]

    report = validate_goal_spec(
        graph,
        _goal(
            goalId="goal.pr-created",
            goalType="sapnexus:PurchaseRequisitionGoal",
            executionMode=execution_mode,
            desiredFactTypes=["sapnexus:PurchaseRequisitionCreatedFact"],
            constraints=[],
        ),
    )

    assert report.valid is expected_valid
    assert [item.code for item in report.issues] == (
        [] if expected_code is None else [expected_code]
    )
    assert report.reachable_fact_types == (
        ("sapnexus:PurchaseRequisitionCreatedFact",) if expected_valid else ()
    )
    assert report.capability_gaps == ()
    assert graph.capabilities[action_id] is action_before


def test_loads_exactly_five_snapshot_sources():
    sources = load_semantic_sources(REPO_ROOT)
    assert tuple(sources.documents_by_path()) == (
        "ontology/capability-relations.yaml",
        "ontology/fact-types.yaml",
        "registry/capabilities.yaml",
        "registry/executor-bindings.yaml",
        "registry/semantic-types.yaml",
    )


def test_snapshot_id_changes_when_catalog_changes():
    sources = load_semantic_sources(REPO_ROOT)
    first = build_registry_snapshot(sources)
    changed = replace(
        sources,
        semantic_types={**dict(sources.semantic_types), "version": 999},
    )
    assert build_registry_snapshot(changed).snapshot_id != first.snapshot_id


def test_loaded_source_tree_rejects_top_level_and_nested_mutation():
    sources = load_semantic_sources(REPO_ROOT)

    with pytest.raises(TypeError):
        sources.capabilities["version"] = 999
    with pytest.raises(TypeError):
        sources.capabilities["capabilities"][0]["name"] = "changed"
    with pytest.raises(AttributeError):
        sources.capabilities["capabilities"].append({})


def test_load_yaml_mapping_wraps_malformed_yaml(tmp_path: Path):
    path = tmp_path / "malformed.yaml"
    path.write_text("root: [unterminated\n", encoding="utf-8")

    with pytest.raises(SourceLoadError, match=str(path)) as exc_info:
        load_yaml_mapping(path)

    assert exc_info.value.path == path
    assert exc_info.value.__cause__ is not None


def test_load_yaml_mapping_wraps_missing_and_unreadable_paths(tmp_path: Path):
    missing_path = tmp_path / "missing.yaml"
    unreadable_path = tmp_path / "directory.yaml"
    unreadable_path.mkdir()

    for path in (missing_path, unreadable_path):
        with pytest.raises(SourceLoadError, match=str(path)) as exc_info:
            load_yaml_mapping(path)
        assert exc_info.value.path == path
        assert isinstance(exc_info.value.__cause__, OSError)


def test_load_yaml_mapping_rejects_non_mapping_root(tmp_path: Path):
    path = tmp_path / "list.yaml"
    path.write_text("- item\n", encoding="utf-8")

    with pytest.raises(SourceLoadError) as exc_info:
        load_yaml_mapping(path)

    assert exc_info.value.path == path
    assert exc_info.value.message == "document root must be a mapping"


def test_canonical_json_ignores_mapping_order_but_preserves_array_order():
    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes(
        {"a": 1, "b": 2}
    )
    assert canonical_json_bytes({"a": [1, 2]}) != canonical_json_bytes(
        {"a": [2, 1]}
    )


def test_registry_snapshot_is_deterministic_and_content_sensitive():
    sources = load_semantic_sources(REPO_ROOT)
    first = build_registry_snapshot(sources)
    second = build_registry_snapshot(sources)
    assert first == second
    assert first.snapshot_id.startswith("sha256:")
    assert len(first.snapshot_id) == 71
    assert tuple(item.path for item in first.sources) == tuple(
        sources.documents_by_path()
    )
    jsonschema.validate(
        first.to_dict(), _load_semantic_schema("registry-snapshot.schema.json")
    )

    changed_capabilities = dict(sources.capabilities)
    changed_capabilities["version"] = 999
    changed = replace(sources, capabilities=changed_capabilities)
    assert build_registry_snapshot(changed).snapshot_id != first.snapshot_id


def test_compiles_expected_immutable_producer_edges():
    result = build_semantic_contracts(load_semantic_sources(REPO_ROOT))
    assert result.report.valid is True
    assert result.report.issues == ()
    assert result.graph is not None
    assert result.snapshot is not None
    assert result.graph.producers_by_fact_type[
        "sapnexus:InventoryAvailabilityFact"
    ] == ("MM.Inventory.GetAvailability",)
    assert result.graph.producers_by_fact_type[
        "sapnexus:PurchaseOrderSupplyFact"
    ] == ("MM.PurchaseOrder.GetList",)
    assert tuple(edge.relation_type for edge in result.graph.edges) == (
        "producesFactType",
        "producesFactType",
        "producesFactType",
    )
    with pytest.raises(TypeError):
        result.graph.capabilities["MM.Inventory.GetAvailability"]["kind"] = "Action"


def test_contract_issues_are_structured_and_deterministically_sorted():
    sources = load_semantic_sources(REPO_ROOT)
    broken = dict(sources.capabilities)
    capabilities = [dict(item) for item in broken["capabilities"]]
    capabilities[0] = dict(capabilities[0])
    capabilities[0]["outputs"] = [dict(item) for item in capabilities[0]["outputs"]]
    capabilities[0]["outputs"][0]["factTypeRef"] = "sapnexus:UnknownFact"
    broken["capabilities"] = capabilities + [dict(capabilities[0])]

    result = build_semantic_contracts(replace(sources, capabilities=broken))
    assert result.report.valid is False
    assert result.graph is None
    assert result.snapshot is None
    assert list(result.report.issues) == sorted(
        result.report.issues,
        key=lambda item: (item.path, item.code, item.message),
    )
    assert {item.code for item in result.report.issues} >= {
        "DUPLICATE_ID",
        "UNKNOWN_FACT_TYPE",
    }


def _mutable_document(document):
    if isinstance(document, dict) or hasattr(document, "items"):
        return {key: _mutable_document(value) for key, value in document.items()}
    if isinstance(document, (list, tuple)):
        return [_mutable_document(value) for value in document]
    return document


def test_schema_invalid_unhashable_id_fails_closed_before_building_artifacts():
    sources = load_semantic_sources(REPO_ROOT)
    fact_types = _mutable_document(sources.fact_types)
    fact_types["factTypes"][0]["factTypeId"] = {"not": "an id"}

    result = build_semantic_contracts(replace(sources, fact_types=fact_types))

    assert result.report.valid is False
    assert result.graph is None
    assert result.snapshot is None
    assert any(
        issue == ValidationIssue(
            path="/factTypes/0/factTypeId",
            code="SCHEMA_INVALID",
            message="{'not': 'an id'} is not of type 'string'",
        )
        for issue in result.report.issues
    )


def mutated_sources(sources, mutation):
    capabilities = _mutable_document(sources.capabilities)
    relations = _mutable_document(sources.relations)
    inventory = capabilities["capabilities"][0]
    purchase_orders = capabilities["capabilities"][1]

    if mutation == "fact-input-without-reference":
        inventory["inputs"][0]["bindingKind"] = "fact"
        inventory["inputs"][0].pop("satisfiableByFactType", None)
    elif mutation == "primary-output-without-fact-type":
        inventory["outputs"][0].pop("factTypeRef")
    elif mutation == "unknown-relation-capability":
        relations["relations"] = [
            {
                "relationId": "relation.unknown-capability",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": "MM.Unknown.Read",
                "dependsOnCapabilityId": purchase_orders["capabilityId"],
            }
        ]
    elif mutation == "unknown-precondition-fact":
        relations["relations"] = [
            {
                "relationId": "relation.unknown-fact",
                "relationType": "precondition",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "requiredFactType": "sapnexus:UnknownFact",
            }
        ]
    elif mutation == "duplicate-authored-relation":
        edge = {
            "relationType": "dependsOn",
            **AUTHORED_RELATION,
            "capabilityId": inventory["capabilityId"],
            "dependsOnCapabilityId": purchase_orders["capabilityId"],
        }
        relations["relations"] = [
            {"relationId": "relation.duplicate-1", **edge},
            {"relationId": "relation.duplicate-2", **edge},
        ]
    elif mutation == "depends-on-cycle":
        relations["relations"] = [
            {
                "relationId": "relation.cycle-1",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "dependsOnCapabilityId": purchase_orders["capabilityId"],
            },
            {
                "relationId": "relation.cycle-2",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": purchase_orders["capabilityId"],
                "dependsOnCapabilityId": inventory["capabilityId"],
            },
        ]
    else:
        raise AssertionError(f"unsupported mutation: {mutation}")

    return replace(sources, capabilities=capabilities, relations=relations)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("fact-input-without-reference", "SCHEMA_INVALID"),
        ("primary-output-without-fact-type", "SCHEMA_INVALID"),
        ("unknown-relation-capability", "RELATION_ENDPOINT_NOT_FOUND"),
        ("unknown-precondition-fact", "RELATION_ENDPOINT_NOT_FOUND"),
        ("duplicate-authored-relation", "DUPLICATE_ID"),
        ("depends-on-cycle", "DEPENDENCY_CYCLE"),
    ],
)
def test_contract_negative_matrix(mutation, expected_code):
    sources = mutated_sources(load_semantic_sources(REPO_ROOT), mutation)
    result = build_semantic_contracts(sources)
    assert result.report.valid is False
    assert expected_code in {item.code for item in result.report.issues}


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("fact-input-without-reference", "satisfiableByFactType is required"),
        ("primary-output-without-fact-type", "factTypeRef is required"),
    ],
)
def test_legacy_validator_enforces_v2_semantic_io_invariants(
    mutation, expected_error
):
    contract = load_registry_contract(REPO_ROOT / "registry/capabilities.yaml")
    capability = contract.capabilities[0]
    raw = deepcopy(capability.raw)
    if mutation == "fact-input-without-reference":
        raw["inputs"][0]["bindingKind"] = "fact"
        raw["inputs"][0].pop("satisfiableByFactType", None)
    elif mutation == "primary-output-without-fact-type":
        raw["outputs"][0].pop("factTypeRef")
    else:
        raise AssertionError(f"unsupported mutation: {mutation}")
    mutated = RegistryContract([replace(capability, raw=raw)])

    errors = validate_registry_contract(mutated, repo_root=REPO_ROOT)

    assert any(expected_error in error for error in errors)


def _replace_source_document(sources, source_name, mutation):
    document = _mutable_document(getattr(sources, source_name))
    mutation(document)
    return replace(sources, **{source_name: document})


def _assert_fail_closed(result, expected_path_codes):
    assert result.report.valid is False
    assert result.graph is None
    assert result.snapshot is None
    assert tuple(
        (issue.path, issue.code) for issue in result.report.issues
    ) == expected_path_codes


def test_exact_duplicate_fact_type_reports_indexed_duplicate_id():
    def mutation(document):
        document["factTypes"].append(deepcopy(document["factTypes"][0]))

    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT), "fact_types", mutation
    )

    result = build_semantic_contracts(sources)

    _assert_fail_closed(result, (("/factTypes/3/factTypeId", "DUPLICATE_ID"),))


def test_exact_duplicate_relation_reports_id_and_semantic_edge_duplicates():
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)["capabilities"]
    relation = {
        "relationId": "relation.exact-duplicate",
        "relationType": "dependsOn",
        **AUTHORED_RELATION,
        "capabilityId": capabilities[0]["capabilityId"],
        "dependsOnCapabilityId": capabilities[1]["capabilityId"],
    }

    def mutation(document):
        document["relations"] = [relation, deepcopy(relation)]

    mutated = _replace_source_document(sources, "relations", mutation)

    result = build_semantic_contracts(mutated)

    _assert_fail_closed(
        result,
        (
            ("/relations/1", "DUPLICATE_ID"),
            ("/relations/1/relationId", "DUPLICATE_ID"),
        ),
    )


def _assert_exact_fail_closed_issues(result, expected_issues):
    assert result.report.valid is False
    assert result.graph is None
    assert result.snapshot is None
    assert result.report.issues == expected_issues
    assert result.report.issues == tuple(
        sorted(
            result.report.issues,
            key=lambda issue: (issue.path, issue.code, issue.message),
        )
    )


def test_mixed_exact_and_same_id_fact_type_duplicates_report_every_later_index():
    def mutation(document):
        original = document["factTypes"][0]
        exact_copy = deepcopy(original)
        different_body = deepcopy(original)
        different_body["name"] = "Different duplicate Fact Type"
        document["factTypes"].extend((exact_copy, different_body))

    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT), "fact_types", mutation
    )

    result = build_semantic_contracts(sources)

    _assert_exact_fail_closed_issues(
        result,
        (
            ValidationIssue(
                path="/factTypes/3/factTypeId",
                code="DUPLICATE_ID",
                message=(
                    "duplicate factTypeId: "
                    "sapnexus:InventoryAvailabilityFact"
                ),
            ),
            ValidationIssue(
                path="/factTypes/4/factTypeId",
                code="DUPLICATE_ID",
                message=(
                    "duplicate factTypeId: "
                    "sapnexus:InventoryAvailabilityFact"
                ),
            ),
        ),
    )


def test_mixed_relation_duplicates_report_every_id_and_semantic_edge_issue():
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)["capabilities"]
    fact_types = _mutable_document(sources.fact_types)["factTypes"]
    base_relation = {
        "relationId": "relation.mixed-duplicate",
        "relationType": "dependsOn",
        **AUTHORED_RELATION,
        "capabilityId": capabilities[0]["capabilityId"],
        "dependsOnCapabilityId": capabilities[1]["capabilityId"],
    }
    same_id_different_edge = {
        "relationId": base_relation["relationId"],
        "relationType": "precondition",
        **AUTHORED_RELATION,
        "capabilityId": capabilities[0]["capabilityId"],
        "requiredFactType": fact_types[0]["factTypeId"],
    }
    same_edge_different_id = {
        **base_relation,
        "relationId": "relation.same-edge-different-id",
    }

    mutated = _replace_source_document(
        sources,
        "relations",
        lambda document: document.__setitem__(
            "relations",
            [
                base_relation,
                deepcopy(base_relation),
                same_id_different_edge,
                same_edge_different_id,
            ],
        ),
    )

    result = build_semantic_contracts(mutated)
    edge = (
        "dependsOn",
        capabilities[0]["capabilityId"],
        capabilities[1]["capabilityId"],
    )

    _assert_exact_fail_closed_issues(
        result,
        (
            ValidationIssue(
                path="/relations/1",
                code="DUPLICATE_ID",
                message=f"duplicate authored semantic edge: {edge!r}",
            ),
            ValidationIssue(
                path="/relations/1/relationId",
                code="DUPLICATE_ID",
                message="duplicate relationId: relation.mixed-duplicate",
            ),
            ValidationIssue(
                path="/relations/2/relationId",
                code="DUPLICATE_ID",
                message="duplicate relationId: relation.mixed-duplicate",
            ),
            ValidationIssue(
                path="/relations/3",
                code="DUPLICATE_ID",
                message=f"duplicate authored semantic edge: {edge!r}",
            ),
        ),
    )


def test_exact_relation_duplicate_does_not_hide_unknown_endpoint_issue():
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)["capabilities"]
    base_relation = {
        "relationId": "relation.exact-with-unknown-endpoint",
        "relationType": "dependsOn",
        **AUTHORED_RELATION,
        "capabilityId": capabilities[0]["capabilityId"],
        "dependsOnCapabilityId": capabilities[1]["capabilityId"],
    }
    unknown_endpoint_relation = {
        "relationId": "relation.unknown-endpoint",
        "relationType": "dependsOn",
        **AUTHORED_RELATION,
        "capabilityId": capabilities[0]["capabilityId"],
        "dependsOnCapabilityId": "MM.Unknown.Read",
    }

    mutated = _replace_source_document(
        sources,
        "relations",
        lambda document: document.__setitem__(
            "relations",
            [base_relation, deepcopy(base_relation), unknown_endpoint_relation],
        ),
    )

    result = build_semantic_contracts(mutated)
    edge = (
        "dependsOn",
        capabilities[0]["capabilityId"],
        capabilities[1]["capabilityId"],
    )

    _assert_exact_fail_closed_issues(
        result,
        (
            ValidationIssue(
                path="/relations/1",
                code="DUPLICATE_ID",
                message=f"duplicate authored semantic edge: {edge!r}",
            ),
            ValidationIssue(
                path="/relations/1/relationId",
                code="DUPLICATE_ID",
                message=(
                    "duplicate relationId: "
                    "relation.exact-with-unknown-endpoint"
                ),
            ),
            ValidationIssue(
                path="/relations/2/dependsOnCapabilityId",
                code="RELATION_ENDPOINT_NOT_FOUND",
                message="relation endpoint not found: 'MM.Unknown.Read'",
            ),
        ),
    )


def _derivable_consumer_sources(relations: list[dict]):
    """Real sources plus a consumer the deriver CAN match, and hand-authored
    relations (T2 task 3.6.3).

    ``MM.Supply.Summarize`` declares one ``bindingKind: fact`` input satisfied
    by ``sapnexus:InventoryAvailabilityFact``, whose ``availableQuantity`` field
    is published by the single active producer ``MM.Inventory.GetAvailability``.
    So ``derive_data_dependencies`` computes that edge, and any hand-authored
    relation for the same pair is redundant by construction.
    """
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)
    consumer = deepcopy(capabilities["capabilities"][1])
    consumer["capabilityId"] = "MM.Supply.Summarize"
    consumer["name"] = "Supply Summary"
    consumer["ontologyIri"] = "sapnexus:MM_Supply_Summarize"
    consumer["semanticType"] = "sapnexus:SupplySummaryReadFunction"
    consumer["inputs"] = [
        {
            "name": "availability0",
            "semanticType": "sapnexus:AvailableQuantity",
            "bindingKind": "fact",
            "satisfiableByFactType": "sapnexus:InventoryAvailabilityFact",
            "required": True,
            "type": "number",
            "sapParameter": "AVAILABILITY_0",
        }
    ]
    capabilities["capabilities"].append(consumer)
    return replace(
        sources,
        capabilities=capabilities,
        relations={"version": 2, "relations": relations},
    )


def test_relation_without_origin_is_rejected():
    """T2 task 3.6.1: ``origin`` is required, not optional.

    Left optional, an unlabelled edge would be indistinguishable from a derived
    one, and the derivability rule below would have nothing to attach to.
    """
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)["capabilities"]
    mutated = _replace_source_document(
        sources,
        "relations",
        lambda document: document.__setitem__(
            "relations",
            [
                {
                    "relationId": "relation.without-origin",
                    "relationType": "dependsOn",
                    "capabilityId": capabilities[0]["capabilityId"],
                    "dependsOnCapabilityId": capabilities[1]["capabilityId"],
                }
            ],
        ),
    )

    result = build_semantic_contracts(mutated)

    assert result.report.valid is False
    assert result.graph is None and result.snapshot is None
    assert [(issue.path, issue.code) for issue in result.report.issues] == [
        ("/relations/0", "SCHEMA_INVALID")
    ]


def test_manual_relation_without_justification_is_rejected():
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)["capabilities"]
    mutated = _replace_source_document(
        sources,
        "relations",
        lambda document: document.__setitem__(
            "relations",
            [
                {
                    "relationId": "relation.manual-without-justification",
                    "relationType": "dependsOn",
                    "origin": "manual",
                    "capabilityId": capabilities[0]["capabilityId"],
                    "dependsOnCapabilityId": capabilities[1]["capabilityId"],
                }
            ],
        ),
    )

    result = build_semantic_contracts(mutated)

    assert result.report.valid is False
    assert result.graph is None and result.snapshot is None
    assert [(issue.path, issue.code) for issue in result.report.issues] == [
        ("/relations/0", "SCHEMA_INVALID")
    ]
    assert "justification" in result.report.issues[0].message


def test_manual_relation_the_deriver_can_compute_is_rejected():
    sources = _derivable_consumer_sources(
        [
            {
                "relationId": "relation.supply-summary-needs-inventory",
                "relationType": "dependsOn",
                "origin": "manual",
                "justification": "asserted by hand to make the catalog non-empty",
                "capabilityId": "MM.Supply.Summarize",
                "dependsOnCapabilityId": "MM.Inventory.GetAvailability",
            }
        ]
    )

    result = build_semantic_contracts(sources)

    _assert_exact_fail_closed_issues(
        result,
        (
            ValidationIssue(
                path="/relations/0",
                code="RELATION_IS_DERIVABLE",
                message=(
                    "authored relation 'relation.supply-summary-needs-inventory' "
                    "duplicates the derivable edge "
                    "'derived.dependsOn.MM.Supply.Summarize~"
                    "MM.Inventory.GetAvailability': MM.Supply.Summarize depends "
                    "on MM.Inventory.GetAvailability; delete it and read the "
                    "derived view instead"
                ),
            ),
        ),
    )


def test_relabelling_a_derivable_relation_as_derived_does_not_admit_it():
    """The rule applies regardless of ``origin`` (T2 task 3.6.2).

    The spec names ``origin: manual``; enforcing only that would leave a
    one-word escape -- relabel the same hand-written edge ``origin: derived``
    and the claim moves without the file changing. The deriver is the authority
    on what is derivable, so the label cannot buy admission either way.
    """
    sources = _derivable_consumer_sources(
        [
            {
                "relationId": "relation.supply-summary-needs-inventory",
                "relationType": "dependsOn",
                "origin": "derived",
                "capabilityId": "MM.Supply.Summarize",
                "dependsOnCapabilityId": "MM.Inventory.GetAvailability",
            }
        ]
    )

    result = build_semantic_contracts(sources)

    assert result.report.valid is False
    assert [(issue.path, issue.code) for issue in result.report.issues] == [
        ("/relations/0", "RELATION_IS_DERIVABLE")
    ]


def test_non_derivable_dependson_and_precondition_still_validate():
    """T2 task 3.6.4: the relation catalog stays authorable.

    ``MM.Supply.Summarize`` here declares no ``satisfiableByFactType``, so the
    deriver computes nothing and both relation types remain hand-authorable
    with ``origin`` and ``justification``.
    """
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)["capabilities"]
    fact_types = _mutable_document(sources.fact_types)["factTypes"]
    mutated = _replace_source_document(
        sources,
        "relations",
        lambda document: document.__setitem__(
            "relations",
            [
                {
                    "relationId": "relation.authored-ordering",
                    "relationType": "dependsOn",
                    "origin": "manual",
                    "justification": (
                        "ordering asserted by process, not implied by any "
                        "Fact Type field"
                    ),
                    "capabilityId": capabilities[0]["capabilityId"],
                    "dependsOnCapabilityId": capabilities[1]["capabilityId"],
                },
                {
                    "relationId": "relation.authored-precondition",
                    "relationType": "precondition",
                    "origin": "manual",
                    "justification": "required Fact Type is a policy gate",
                    "capabilityId": capabilities[0]["capabilityId"],
                    "requiredFactType": fact_types[0]["factTypeId"],
                },
            ],
        ),
    )

    result = build_semantic_contracts(mutated)

    assert result.report.issues == ()
    assert result.report.valid is True
    assert result.graph is not None and result.snapshot is not None


def test_independent_same_path_schema_violations_are_all_preserved():
    def mutation(document):
        document["bindings"][0]["constraints"]["timeoutMs"] = 0.5

    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT), "executor_bindings", mutation
    )

    result = build_semantic_contracts(sources)

    _assert_fail_closed(
        result,
        (
            ("/bindings/0/constraints/timeoutMs", "SCHEMA_INVALID"),
            ("/bindings/0/constraints/timeoutMs", "SCHEMA_INVALID"),
        ),
    )
    assert tuple(issue.message for issue in result.report.issues) == tuple(
        sorted(
            (
                "0.5 is less than the minimum of 1",
                "0.5 is not of type 'integer'",
            )
        )
    )


@pytest.mark.parametrize(
    ("source_name", "mutation", "expected_path"),
    [
        (
            "capabilities",
            lambda document: document.__setitem__("version", True),
            (
                "/capabilityRegistry/version",
                "/capabilityRegistry/version",
            ),
        ),
        (
            "capabilities",
            lambda document: document.__setitem__("version", 3),
            "/capabilityRegistry/version",
        ),
        (
            "capabilities",
            lambda document: document.__setitem__("capabilities", []),
            "/capabilities",
        ),
        (
            "capabilities",
            lambda document: document["capabilities"][0].pop("name"),
            "/capabilities/0/name",
        ),
        (
            "capabilities",
            lambda document: document["capabilities"][0]["inputs"][0].__setitem__(
                "required", 1
            ),
            "/capabilities/0/inputs/0/required",
        ),
        (
            "capabilities",
            lambda document: document["capabilities"][0].__setitem__(
                "status", "unknown"
            ),
            "/capabilities/0/status",
        ),
        (
            "capabilities",
            lambda document: document["capabilities"][0].__setitem__(
                "unexpected", "value"
            ),
            "/capabilities/0/unexpected",
        ),
        (
            "executor_bindings",
            lambda document: document.__setitem__("bindings", []),
            "/bindings",
        ),
        (
            "executor_bindings",
            lambda document: document["bindings"][0].pop("constraints"),
            "/bindings/0/constraints",
        ),
        (
            "executor_bindings",
            lambda document: document.__setitem__("version", 2),
            "/executorBindingCatalog/version",
        ),
        (
            "fact_types",
            lambda document: document["factTypes"][0].pop("name"),
            "/factTypes/0/name",
        ),
        (
            "fact_types",
            # The catalog is now at version 3 (derived-parameter-binding added
            # `fields` at v2, then `valueTypes` at v3), so 4 is the off-by-one
            # that must fail closed. This number MUST move with every version
            # bump: pinning it at the current valid version turns the mutation
            # into a no-op and the case silently stops testing anything.
            lambda document: document.__setitem__("version", 4),
            "/factTypeCatalog/version",
        ),
        (
            "fact_types",
            lambda document: document["factTypes"][0].__setitem__("keyedBy", []),
            "/factTypes/0/keyedBy",
        ),
        (
            "relations",
            lambda document: document.__setitem__(
                "relations",
                [
                    {
                        "relationId": "relation.invalid-shape",
                        "relationType": "dependsOn",
                        **AUTHORED_RELATION,
                        "capabilityId": "MM.Inventory.GetAvailability",
                        "requiredFactType": "sapnexus:InventoryAvailabilityFact",
                    }
                ],
            ),
            "/relations/0",
        ),
        (
            "relations",
            lambda document: document.__setitem__("version", 3),
            "/capabilityRelationCatalog/version",
        ),
    ],
    ids=[
        "boolean-is-not-version-integer",
        "capabilities-exact-version",
        "capabilities-min-items",
        "capability-required-field",
        "json-schema-boolean-type",
        "capability-enum",
        "capability-additional-property",
        "bindings-min-items",
        "binding-required-field",
        "binding-exact-version",
        "fact-type-required-field",
        "fact-type-exact-version",
        "fact-type-key-min-items",
        "relation-one-of",
        "relations-exact-version",
    ],
)
def test_complete_source_schema_matrix_fails_closed(
    source_name, mutation, expected_path
):
    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT), source_name, mutation
    )

    result = build_semantic_contracts(sources)

    expected_paths = (
        (expected_path,) if isinstance(expected_path, str) else expected_path
    )
    _assert_fail_closed(
        result,
        tuple((path, "SCHEMA_INVALID") for path in expected_paths),
    )


@pytest.mark.parametrize(
    ("source_name", "mutation", "expected_paths"),
    [
        (
            "fact_types",
            lambda document: document["factTypes"][0].__setitem__(
                "keyedBy", {"material"}
            ),
            ("/factTypes/0/keyedBy",),
        ),
        (
            "fact_types",
            lambda document: document["factTypes"][0].__setitem__(
                "description", date(2026, 7, 19)
            ),
            ("/factTypes/0/description",),
        ),
        (
            "fact_types",
            lambda document: document["factTypes"][0].__setitem__(
                "description", b"binary"
            ),
            ("/factTypes/0/description",),
        ),
        (
            "fact_types",
            lambda document: document["factTypes"][0].__setitem__(
                "description", float("nan")
            ),
            ("/factTypes/0/description",),
        ),
        (
            "capabilities",
            lambda document: document["capabilities"][0].__setitem__(
                "unexpected", {"mutable"}
            ),
            (
                "/capabilities/0/unexpected",
                "/capabilities/0/unexpected",
            ),
        ),
        (
            "capabilities",
            lambda document: document["capabilities"][0]["outputs"][0].__setitem__(
                "factTypeRef", {"unsupported"}
            ),
            ("/capabilities/0/outputs/0/factTypeRef",),
        ),
        (
            "capabilities",
            lambda document: document["capabilities"][0]["executor"][
                "inputMapping"
            ].__setitem__(("not", "a", "json", "key"), "MATERIAL"),
            ("/capabilities/0/executor/inputMapping",),
        ),
    ],
    ids=[
        "yaml-set",
        "yaml-timestamp",
        "yaml-binary",
        "non-finite-number",
        "nested-mutable-set",
        "fact-reference-conversion-placeholder",
        "non-string-key",
    ],
)
def test_non_json_source_values_fail_closed(source_name, mutation, expected_paths):
    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT), source_name, mutation
    )

    result = build_semantic_contracts(sources)

    _assert_fail_closed(
        result,
        tuple((path, "SCHEMA_INVALID") for path in expected_paths),
    )


@pytest.mark.parametrize(
    ("source_name", "expected_path"),
    [
        ("capabilities", "/capabilityRegistry"),
        ("executor_bindings", "/executorBindingCatalog"),
        ("fact_types", "/factTypeCatalog"),
        ("relations", "/capabilityRelationCatalog"),
    ],
)
def test_non_mapping_source_roots_fail_closed(source_name, expected_path):
    sources = replace(
        load_semantic_sources(REPO_ROOT), **{source_name: "truthy-scalar"}
    )

    result = build_semantic_contracts(sources)

    _assert_fail_closed(result, ((expected_path, "SCHEMA_INVALID"),))


@pytest.mark.parametrize(
    ("source_name", "collection_name", "root_path", "collection_path"),
    [
        ("capabilities", "capabilities", "/capabilityRegistry", "/capabilities"),
        (
            "executor_bindings",
            "bindings",
            "/executorBindingCatalog",
            "/bindings",
        ),
        ("fact_types", "factTypes", "/factTypeCatalog", "/factTypes"),
        (
            "relations",
            "relations",
            "/capabilityRelationCatalog",
            "/relations",
        ),
    ],
)
def test_source_root_and_collection_paths_are_unambiguous(
    source_name, collection_name, root_path, collection_path
):
    sources = load_semantic_sources(REPO_ROOT)
    malformed_root = replace(sources, **{source_name: "truthy-scalar"})
    malformed_collection = _replace_source_document(
        sources,
        source_name,
        lambda document: document.__setitem__(collection_name, "truthy-scalar"),
    )

    _assert_fail_closed(
        build_semantic_contracts(malformed_root),
        ((root_path, "SCHEMA_INVALID"),),
    )
    _assert_fail_closed(
        build_semantic_contracts(malformed_collection),
        ((collection_path, "SCHEMA_INVALID"),),
    )


@pytest.mark.parametrize("field_name", ["inputs", "outputs"])
@pytest.mark.parametrize(
    ("malformed_value", "path_suffix"),
    [
        (1, ""),
        ({"truthy": "mapping"}, ""),
        ("truthy-string", ""),
        (["malformed-item"], "/0"),
    ],
    ids=["scalar", "mapping", "string", "malformed-item"],
)
def test_semantic_builder_malformed_io_containers_fail_closed(
    field_name, malformed_value, path_suffix
):
    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT),
        "capabilities",
        lambda document: document["capabilities"][0].__setitem__(
            field_name, malformed_value
        ),
    )

    result = build_semantic_contracts(sources)

    # One SCHEMA_INVALID per malformed container: the `ioField` object-type
    # check. Dropping the identifier `not.required` branch removed a spurious
    # second error ("should not be valid under {'required': [...]}") that the
    # branch produced when applied to a non-object.
    expected_count = 1
    _assert_fail_closed(
        result,
        tuple(
            (f"/capabilities/0/{field_name}{path_suffix}", "SCHEMA_INVALID")
            for _ in range(expected_count)
        ),
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("satisfiableByFactType", []), ("factTypeRef", [])],
)
def test_wrong_type_fact_reference_has_one_canonical_schema_issue(
    field_name, value
):
    field_group = "inputs" if field_name == "satisfiableByFactType" else "outputs"

    def mutation(document):
        document["capabilities"][0][field_group][0][field_name] = value

    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT), "capabilities", mutation
    )

    result = build_semantic_contracts(sources)

    _assert_fail_closed(
        result,
        ((f"/capabilities/0/{field_group}/0/{field_name}", "SCHEMA_INVALID"),),
    )


@pytest.mark.parametrize("field_name", ["inputs", "outputs"])
@pytest.mark.parametrize(
    "malformed_value",
    [1, {"truthy": "mapping"}, "truthy-string", ["malformed-item"]],
    ids=["scalar", "mapping", "string", "malformed-item"],
)
def test_legacy_validator_malformed_io_containers_return_errors(
    field_name, malformed_value
):
    contract = load_registry_contract(REPO_ROOT / "registry/capabilities.yaml")
    capability = contract.capabilities[0]
    raw = deepcopy(capability.raw)
    raw[field_name] = malformed_value

    errors = validate_registry_contract(
        RegistryContract([replace(capability, raw=raw)]), repo_root=REPO_ROOT
    )

    assert isinstance(errors, list)
    expected = (
        f"{field_name}[<unknown>].name is required"
        if isinstance(malformed_value, list)
        else f"{field_name} are required"
    )
    assert any(expected in error for error in errors)


def test_graph_compiler_rejects_unsupported_mutable_values():
    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT),
        "capabilities",
        lambda document: document["capabilities"][0].__setitem__(
            "unsupported", {"mutable"}
        ),
    )

    with pytest.raises(TypeError, match="unsupported graph value"):
        SemanticGraphCompiler().compile(sources)


@pytest.mark.parametrize(
    "non_finite", [float("nan"), float("inf"), float("-inf")]
)
def test_graph_compiler_rejects_non_finite_numbers(non_finite):
    sources = _replace_source_document(
        load_semantic_sources(REPO_ROOT),
        "fact_types",
        lambda document: document["factTypes"][0].__setitem__(
            "description", non_finite
        ),
    )

    with pytest.raises(TypeError, match="unsupported graph value: non-finite float"):
        SemanticGraphCompiler().compile(sources)


def _semantic_rule_sources(mutation):
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)
    bindings = _mutable_document(sources.executor_bindings)
    fact_types = _mutable_document(sources.fact_types)
    relations = _mutable_document(sources.relations)
    inventory = capabilities["capabilities"][0]
    purchase_orders = capabilities["capabilities"][1]

    if mutation == "duplicate-capability-id":
        duplicate = deepcopy(inventory)
        duplicate["name"] = "Duplicate capability"
        capabilities["capabilities"].append(duplicate)
    elif mutation == "duplicate-fact-type-id":
        duplicate = deepcopy(fact_types["factTypes"][0])
        duplicate["name"] = "Duplicate Fact Type"
        fact_types["factTypes"].append(duplicate)
    elif mutation == "duplicate-relation-id":
        relations["relations"] = [
            {
                "relationId": "relation.duplicate-id",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "dependsOnCapabilityId": purchase_orders["capabilityId"],
            },
            {
                "relationId": "relation.duplicate-id",
                "relationType": "precondition",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "requiredFactType": fact_types["factTypes"][0]["factTypeId"],
            },
        ]
    elif mutation == "duplicate-binding-id":
        duplicate = deepcopy(bindings["bindings"][0])
        duplicate["constraints"]["timeoutMs"] += 1
        bindings["bindings"].append(duplicate)
    elif mutation == "binding-id-missing":
        inventory["executorBinding"].pop("bindingId")
    elif mutation == "binding-id-unknown":
        inventory["executorBinding"]["bindingId"] = "binding.unknown"
    elif mutation == "binding-type-mismatch":
        inventory["executorBinding"]["type"] = "ODATA"
    elif mutation == "binding-types-both-missing":
        inventory["executorBinding"].pop("type")
        bindings["bindings"][0].pop("type")
    elif mutation == "fact-input-reference-missing":
        inventory["inputs"][0]["bindingKind"] = "fact"
        inventory["inputs"][0].pop("satisfiableByFactType", None)
    elif mutation == "primary-output-reference-missing":
        inventory["outputs"][0].pop("factTypeRef")
    elif mutation == "unknown-input-fact-reference":
        inventory["inputs"][0]["bindingKind"] = "fact"
        inventory["inputs"][0]["satisfiableByFactType"] = "sapnexus:UnknownFact"
    elif mutation == "unknown-output-fact-reference":
        inventory["outputs"][0]["factTypeRef"] = "sapnexus:UnknownFact"
    elif mutation == "authored-relation-not-allowed":
        relations["relations"] = [
            {
                "relationId": "relation.producer",
                "relationType": "producesFactType",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "requiredFactType": fact_types["factTypes"][0]["factTypeId"],
            }
        ]
    elif mutation == "unknown-relation-capability":
        relations["relations"] = [
            {
                "relationId": "relation.unknown-capability",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": "MM.Unknown.Read",
                "dependsOnCapabilityId": purchase_orders["capabilityId"],
            }
        ]
    elif mutation == "unknown-dependency-capability":
        relations["relations"] = [
            {
                "relationId": "relation.unknown-dependency",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "dependsOnCapabilityId": "MM.Unknown.Read",
            }
        ]
    elif mutation == "unknown-precondition-fact":
        relations["relations"] = [
            {
                "relationId": "relation.unknown-fact",
                "relationType": "precondition",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "requiredFactType": "sapnexus:UnknownFact",
            }
        ]
    elif mutation == "duplicate-authored-edge":
        edge = {
            "relationType": "dependsOn",
            **AUTHORED_RELATION,
            "capabilityId": inventory["capabilityId"],
            "dependsOnCapabilityId": purchase_orders["capabilityId"],
        }
        relations["relations"] = [
            {"relationId": "relation.edge-1", **edge},
            {"relationId": "relation.edge-2", **edge},
        ]
    elif mutation == "dependency-self-edge":
        relations["relations"] = [
            {
                "relationId": "relation.self",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "dependsOnCapabilityId": inventory["capabilityId"],
            }
        ]
    elif mutation == "dependency-cycle":
        relations["relations"] = [
            {
                "relationId": "relation.cycle-1",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": inventory["capabilityId"],
                "dependsOnCapabilityId": purchase_orders["capabilityId"],
            },
            {
                "relationId": "relation.cycle-2",
                "relationType": "dependsOn",
                **AUTHORED_RELATION,
                "capabilityId": purchase_orders["capabilityId"],
                "dependsOnCapabilityId": inventory["capabilityId"],
            },
        ]
    else:
        raise AssertionError(f"unsupported mutation: {mutation}")

    return replace(
        sources,
        capabilities=capabilities,
        executor_bindings=bindings,
        fact_types=fact_types,
        relations=relations,
    )


@pytest.mark.parametrize(
    ("mutation", "expected_path_codes"),
    [
        ("duplicate-capability-id", (("/capabilities/3/capabilityId", "DUPLICATE_ID"),)),
        ("duplicate-fact-type-id", (("/factTypes/3/factTypeId", "DUPLICATE_ID"),)),
        ("duplicate-relation-id", (("/relations/1/relationId", "DUPLICATE_ID"),)),
        ("duplicate-binding-id", (("/bindings/3/bindingId", "DUPLICATE_ID"),)),
        (
            "binding-id-missing",
            (("/capabilities/0/executorBinding/bindingId", "SCHEMA_INVALID"),),
        ),
        (
            "binding-id-unknown",
            (("/capabilities/0/executorBinding/bindingId", "SCHEMA_INVALID"),),
        ),
        (
            "binding-type-mismatch",
            (("/capabilities/0/executorBinding/type", "SCHEMA_INVALID"),),
        ),
        (
            "binding-types-both-missing",
            (
                ("/bindings/0/type", "SCHEMA_INVALID"),
                ("/capabilities/0/executorBinding/type", "SCHEMA_INVALID"),
            ),
        ),
        (
            "fact-input-reference-missing",
            (("/capabilities/0/inputs/0/satisfiableByFactType", "SCHEMA_INVALID"),),
        ),
        (
            "primary-output-reference-missing",
            (("/capabilities/0/outputs/0/factTypeRef", "SCHEMA_INVALID"),),
        ),
        (
            "unknown-input-fact-reference",
            (("/capabilities/0/inputs/0/satisfiableByFactType", "UNKNOWN_FACT_TYPE"),),
        ),
        (
            "unknown-output-fact-reference",
            # Repointing the producer's `factTypeRef` away from
            # `sapnexus:InventoryAvailabilityFact` does two things, and both are
            # real: the reference dangles, AND the catalog's `availableQuantity`
            # field (cardinality `one`) is left with no active capability
            # publishing it. The publication rule reports the second.
            (
                ("/capabilities/0/outputs/0/factTypeRef", "UNKNOWN_FACT_TYPE"),
                ("/factTypes/0/fields/0/name", "UNPUBLISHED_FACT_FIELD"),
            ),
        ),
        ("authored-relation-not-allowed", (("/relations/0", "SCHEMA_INVALID"),)),
        (
            "unknown-relation-capability",
            (("/relations/0/capabilityId", "RELATION_ENDPOINT_NOT_FOUND"),),
        ),
        (
            "unknown-dependency-capability",
            (("/relations/0/dependsOnCapabilityId", "RELATION_ENDPOINT_NOT_FOUND"),),
        ),
        (
            "unknown-precondition-fact",
            (("/relations/0/requiredFactType", "RELATION_ENDPOINT_NOT_FOUND"),),
        ),
        ("duplicate-authored-edge", (("/relations/1", "DUPLICATE_ID"),)),
        (
            "dependency-self-edge",
            (("/relations/0/dependsOnCapabilityId", "DEPENDENCY_CYCLE"),),
        ),
        (
            "dependency-cycle",
            (("/relations/1/dependsOnCapabilityId", "DEPENDENCY_CYCLE"),),
        ),
    ],
)
def test_semantic_rule_matrix_has_exact_sorted_issues_and_no_artifacts(
    mutation, expected_path_codes
):
    result = build_semantic_contracts(_semantic_rule_sources(mutation))

    _assert_fail_closed(result, expected_path_codes)


def test_graph_records_provenance_folds_derived_edges_and_is_deeply_immutable():
    sources = load_semantic_sources(REPO_ROOT)
    capabilities = _mutable_document(sources.capabilities)
    relations = _mutable_document(sources.relations)
    inventory = capabilities["capabilities"][0]
    purchase_orders = capabilities["capabilities"][1]
    inventory_fact = inventory["outputs"][0]["factTypeRef"]
    inventory["inputs"][0]["bindingKind"] = "fact"
    inventory["inputs"][0]["satisfiableByFactType"] = inventory_fact
    inventory["outputs"].append(deepcopy(inventory["outputs"][0]))
    relations["relations"] = [
        {
            "relationId": "relation.depends",
            "relationType": "dependsOn",
            **AUTHORED_RELATION,
            "capabilityId": inventory["capabilityId"],
            "dependsOnCapabilityId": purchase_orders["capabilityId"],
        },
        {
            "relationId": "relation.precondition",
            "relationType": "precondition",
            **AUTHORED_RELATION,
            "capabilityId": purchase_orders["capabilityId"],
            "requiredFactType": inventory_fact,
        },
    ]
    result = build_semantic_contracts(
        replace(sources, capabilities=capabilities, relations=relations)
    )

    assert result.report.valid is True
    assert result.graph is not None
    graph = result.graph
    edge_tuples = tuple(
        (edge.relation_type, edge.source_id, edge.target_id) for edge in graph.edges
    )
    assert edge_tuples.count(
        ("producesFactType", inventory["capabilityId"], inventory_fact)
    ) == 1
    assert ("consumesFactType", inventory["capabilityId"], inventory_fact) in edge_tuples
    assert (
        "dependsOn",
        inventory["capabilityId"],
        purchase_orders["capabilityId"],
    ) in edge_tuples
    assert (
        "precondition",
        purchase_orders["capabilityId"],
        inventory_fact,
    ) in edge_tuples
    assert graph.consumers_by_fact_type[inventory_fact] == (
        inventory["capabilityId"],
    )

    with pytest.raises(TypeError):
        graph.capabilities[inventory["capabilityId"]] = {}
    with pytest.raises(TypeError):
        graph.capabilities[inventory["capabilityId"]]["executor"]["type"] = "ODATA"
    with pytest.raises(AttributeError):
        graph.capabilities[inventory["capabilityId"]]["outputs"].append({})
    with pytest.raises(AttributeError):
        graph.fact_types[inventory_fact]["keyedBy"].append("other")
    with pytest.raises(AttributeError):
        graph.edges[0].source_id = "changed"
    with pytest.raises(TypeError):
        graph.producers_by_fact_type[inventory_fact] = ()
    with pytest.raises(AttributeError):
        graph.producers_by_fact_type[inventory_fact].append("changed")
    with pytest.raises(TypeError):
        graph.consumers_by_fact_type[inventory_fact] = ()


def test_semantic_planning_cli_validates_legacy_and_semantic_contracts():
    completed = subprocess.run(
        [sys.executable, "scripts/validate-semantic-planning-contract.py"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert re.fullmatch(
        r"Legacy registry contract valid\n"
        r"Semantic planning contract valid: snapshotId=sha256:[0-9a-f]{64}\n",
        completed.stdout,
    )


def test_semantic_planning_cli_stops_after_legacy_failure(monkeypatch, capsys):
    cli = _load_semantic_cli_module()
    monkeypatch.setattr(cli, "load_registry_contract", lambda path: object())
    monkeypatch.setattr(
        cli,
        "validate_registry_contract",
        lambda contract, repo_root: ["invalid legacy registry"],
    )

    def semantic_load_must_not_run(repo_root):
        raise AssertionError("semantic sources loaded after legacy failure")

    monkeypatch.setattr(cli, "load_semantic_sources", semantic_load_must_not_run)

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "legacy: invalid legacy registry\n"


def test_semantic_planning_cli_reports_source_load_failure(monkeypatch, capsys):
    cli = _load_semantic_cli_module()
    source_path = REPO_ROOT / "ontology/fact-types.yaml"
    monkeypatch.setattr(cli, "validate_registry_contract", lambda *args, **kwargs: [])

    def fail_source_load(repo_root):
        raise SourceLoadError(source_path, "malformed source")

    monkeypatch.setattr(cli, "load_semantic_sources", fail_source_load)

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "Legacy registry contract valid\n"
    assert captured.err == f"SCHEMA_INVALID {source_path}: malformed source\n"


def test_semantic_planning_cli_reports_contract_issues(monkeypatch, capsys):
    cli = _load_semantic_cli_module()
    issue = ValidationIssue(
        path="/factTypes/0/factTypeId",
        code="UNKNOWN_FACT_TYPE",
        message="unknown semantic fact",
    )
    invalid_result = SimpleNamespace(
        report=SimpleNamespace(valid=False, issues=(issue,)),
        snapshot=None,
    )
    monkeypatch.setattr(cli, "validate_registry_contract", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "load_semantic_sources", lambda repo_root: object())
    monkeypatch.setattr(cli, "build_semantic_contracts", lambda sources: invalid_result)

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "Legacy registry contract valid\n"
    assert captured.err == (
        "UNKNOWN_FACT_TYPE /factTypes/0/factTypeId: unknown semantic fact\n"
    )


def test_semantic_cli_test_loader_restores_sys_path(monkeypatch):
    excluded_roots = {REPO_ROOT.resolve(), (REPO_ROOT / "agent").resolve()}
    isolated_path = [
        entry
        for entry in sys.path
        if Path(entry or ".").resolve() not in excluded_roots
    ]
    monkeypatch.setattr(sys, "path", isolated_path.copy())
    original_path_object = sys.path

    _load_semantic_cli_module()

    assert sys.path is original_path_object
    assert sys.path == isolated_path


def test_semantic_cli_test_loader_uses_unique_unregistered_modules():
    first = _load_semantic_cli_module()
    second = _load_semantic_cli_module()

    assert first.__name__ != second.__name__
    assert first.__name__ not in sys.modules
    assert second.__name__ not in sys.modules


def test_agent_evidence_script_preserves_release_gate_order():
    _assert_evidence_script_contract(_load_evidence_script())


def test_agent_evidence_script_loader_preserves_raw_newlines(tmp_path):
    evidence_path = tmp_path / "evidence.sh"
    evidence_path.write_bytes(b"first\rsecond\r\nthird\n")

    assert _load_evidence_script(evidence_path) == "first\rsecond\r\nthird\n"


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_agent_evidence_script_guard_accepts_lf_and_crlf(line_ending):
    script = _load_evidence_script().replace("\n", line_ending)

    _assert_evidence_script_contract(script)


def test_agent_evidence_script_guard_requires_fail_fast_directive():
    mutated = _load_evidence_script().replace("set -euo pipefail\n", "", 1)

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(mutated)


def test_agent_evidence_script_guard_requires_fail_fast_before_all_gates():
    script = _load_evidence_script()
    mutated = script.replace("set -euo pipefail\n", "", 1).rstrip()
    mutated = f"{mutated}\nset -euo pipefail\n"

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(mutated)


@pytest.mark.parametrize(
    "mutated",
    [
        lambda script: script.replace('"$PYTHON_BIN"', "$PYTHON_BIN", 1),
        lambda script: script.replace(
            '"$PYTHON_BIN" -m pytest agent/tests',
            'PYTHONPATH=/tmp "$PYTHON_BIN" -m pytest agent/tests',
            1,
        ),
        lambda script: script.replace(
            'PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"',
            'PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"\n'
            "PROBE=$(unexpected-command)",
            1,
        ),
    ],
)
def test_agent_evidence_script_guard_rejects_shell_semantic_mutations(mutated):
    script = mutated(_load_evidence_script())

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(script)


@pytest.mark.parametrize(
    "separator",
    ["\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
)
@pytest.mark.parametrize(
    "hidden_shell_syntax",
    [
        "#; unexpected-command",
        "#&& unexpected-command",
        "#| unexpected-command",
        "#> unexpected-file",
        "#$(unexpected-command)",
    ],
)
def test_agent_evidence_script_guard_rejects_non_lf_hidden_shell_syntax(
    separator,
    hidden_shell_syntax,
):
    assignment = 'PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"'
    mutated = _load_evidence_script().replace(
        assignment,
        f"{assignment}{separator}{hidden_shell_syntax}",
        1,
    )

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(mutated)


@pytest.mark.parametrize(
    "forbidden_character",
    ["\x00", "\x01", "\x7f", "\u00a0", "\u2003", "\u200b"],
)
def test_agent_evidence_script_guard_rejects_forbidden_characters_inside_comments(
    forbidden_character,
):
    mutated = _load_evidence_script().replace(
        "#!/usr/bin/env bash\n",
        f"#!/usr/bin/env bash{forbidden_character}\n",
        1,
    )

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(mutated)


@pytest.mark.parametrize("edge_whitespace", ["\u00a0", "\u2003"])
def test_agent_evidence_script_guard_rejects_non_space_tab_edge_whitespace(
    edge_whitespace,
):
    assignment = 'PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"'
    mutated = _load_evidence_script().replace(
        assignment,
        f"{assignment}{edge_whitespace}",
        1,
    )

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(mutated)


def test_agent_evidence_script_guard_rejects_indented_duplicate_command():
    command = '"$PYTHON_BIN" -m pytest agent/tests'
    mutated = _load_evidence_script().replace(
        command,
        f"{command}\n    {command} # duplicate",
        1,
    )

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(mutated)


def test_agent_evidence_script_guard_rejects_missing_and_reordered_commands():
    script = _load_evidence_script()
    inventory = (
        '"$PYTHON_BIN" -m sap_nexus_agent.eval '
        "evals/inventory_availability_cases.yaml"
    )
    seed = (
        '"$PYTHON_BIN" -m sap_nexus_agent.eval '
        "evals/eval_harness_seed_cases.json"
    )
    missing = script.replace(f"{inventory}\n", "", 1)
    reordered = script.replace(f"{inventory}\n{seed}", f"{seed}\n{inventory}", 1)

    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(missing)
    with pytest.raises(AssertionError):
        _assert_evidence_script_contract(reordered)


def test_agent_evidence_script_guard_ignores_indentation_and_inline_comments():
    formatted_lines = ["", "\t", "    # release gate contract", "\t# next gate"]
    for line in _load_evidence_script().splitlines():
        if line in EXPECTED_EVIDENCE_ACTIVE_LINES:
            formatted_lines.append(f"\t{line}\t # equivalent shell line")
        else:
            formatted_lines.append(line)

    _assert_evidence_script_contract("\n".join(formatted_lines))


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('command "# quoted" # comment', 'command "# quoted"'),
        ("command '# quoted' # comment", "command '# quoted'"),
        (r"command \#escaped # comment", r"command \#escaped"),
        ("command#active # comment", "command#active"),
    ],
)
def test_shell_inline_comment_stripper_preserves_active_hashes(line, expected):
    assert _strip_shell_inline_comment(line) == expected
