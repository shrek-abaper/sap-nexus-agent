from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any

import jsonschema

from .contracts import (
    ContractBuildResult,
    ContractValidationReport,
    GoalReachabilityReport,
    PlanValidationReport,
    RegistrySnapshot,
    SemanticSourceDocuments,
    ValidationIssue,
    sorted_issues,
)
from .graph import ImmutableSemanticGraph, SemanticGraphCompiler
from .snapshot import build_registry_snapshot


def build_semantic_contracts(sources: SemanticSourceDocuments) -> ContractBuildResult:
    schema_issues: list[ValidationIssue] = []
    duplicate_issues = _validate_source_schemas(sources, schema_issues)
    if schema_issues:
        return _invalid_result([*schema_issues, *duplicate_issues])
    issues = list(duplicate_issues)
    _validate_executor_bindings(sources, issues)
    _validate_unique_ids(sources, issues)
    _validate_fact_references(sources, issues)
    _validate_fact_type_fields(sources, issues)
    _validate_relation_endpoints(sources, issues)
    _validate_dependency_cycles(sources, issues)
    if issues:
        return _invalid_result(issues)
    graph = SemanticGraphCompiler().compile(sources)
    snapshot = build_registry_snapshot(sources)
    return ContractBuildResult(
        report=ContractValidationReport(valid=True, issues=()),
        graph=graph,
        snapshot=snapshot,
    )


def validate_goal_spec(
    graph: ImmutableSemanticGraph,
    goal_spec: dict[str, Any],
) -> GoalReachabilityReport:
    issues: list[ValidationIssue] = []
    normalized_goal = _validate_goal_shape(goal_spec, issues)
    if issues:
        return GoalReachabilityReport(
            valid=False,
            issues=_canonical_issues(issues),
            reachable_fact_types=(),
            capability_gaps=(),
        )

    mode = normalized_goal["executionMode"]
    reachable: list[str] = []
    gaps: list[str] = []
    for index, fact_type_id in enumerate(normalized_goal["desiredFactTypes"]):
        path = f"/desiredFactTypes/{index}"
        if fact_type_id not in graph.fact_types:
            issues.append(
                ValidationIssue(
                    path,
                    "UNKNOWN_FACT_TYPE",
                    f"{fact_type_id} is not published",
                )
            )
            continue
        active = tuple(
            capability_id
            for capability_id in graph.producers_by_fact_type.get(fact_type_id, ())
            if graph.capabilities[capability_id]["status"] == "active"
        )
        if not active:
            gaps.append(fact_type_id)
            issues.append(
                ValidationIssue(
                    path,
                    "CAPABILITY_GAP",
                    f"{fact_type_id} has no active producer",
                )
            )
            continue
        eligible = tuple(
            capability_id
            for capability_id in active
            if mode != "READ_ONLY"
            or _is_read_only(graph.capabilities[capability_id])
        )
        if not eligible:
            issues.append(
                ValidationIssue(
                    path,
                    "GOVERNANCE_VIOLATION",
                    f"{fact_type_id} has no READ_ONLY-compatible active producer",
                )
            )
            continue
        reachable.append(fact_type_id)

    ordered = _canonical_issues(issues)
    return GoalReachabilityReport(
        valid=not ordered,
        issues=ordered,
        reachable_fact_types=tuple(sorted(set(reachable))),
        capability_gaps=tuple(sorted(set(gaps))),
    )


def validate_plan_graph(
    graph: ImmutableSemanticGraph,
    snapshot: RegistrySnapshot,
    goal_spec: dict[str, Any],
    plan_graph: dict[str, Any],
) -> PlanValidationReport:
    issues: list[ValidationIssue] = []
    normalized_plan = _validate_plan_shape(plan_graph, issues)
    if issues:
        return PlanValidationReport(False, _canonical_issues(issues))

    _validate_snapshot_and_goal_identity(
        snapshot, goal_spec, normalized_plan, issues
    )
    node_index = _validate_nodes_and_projections(
        graph, normalized_plan, issues
    )
    _validate_parameter_sources(graph, goal_spec, node_index, issues)
    _validate_edges(graph, node_index, normalized_plan, issues)
    _validate_topological_order(node_index, normalized_plan, issues)
    _validate_plan_governance(goal_spec, node_index, issues)
    _validate_goal_outputs(goal_spec, node_index, normalized_plan, issues)
    ordered = _canonical_issues(issues)
    return PlanValidationReport(valid=not ordered, issues=ordered)


def _validate_plan_shape(
    plan_graph: Any,
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    candidates: list[tuple[str, ValidationIssue]] = []
    normalized = _to_json_value(
        plan_graph,
        (),
        "",
        "__plan__",
        "",
        candidates,
    )
    conversion_issues = [issue for _, issue in candidates]
    conversion_paths = {issue.path for issue in conversion_issues}
    issues.extend(conversion_issues)

    validator = jsonschema.Draft202012Validator(
        _load_schema("plan-graph.schema.json")
    )
    errors = sorted(
        validator.iter_errors(normalized),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
            error.message,
        ),
    )
    for error in errors:
        if _plan_unique_items_is_semantic(error):
            continue
        if _unique_items_is_conversion_artifact(error, conversion_paths):
            continue
        for tokens, message in _plan_schema_error_details(error):
            path = "".join(f"/{_pointer_token(token)}" for token in tokens)
            if error.instance is None and path in conversion_paths:
                continue
            issues.append(ValidationIssue(path, "SCHEMA_INVALID", message))

    if isinstance(normalized, dict):
        _validate_plan_stable_ids(normalized, issues)
        return normalized
    return {}


def _plan_unique_items_is_semantic(
    error: jsonschema.ValidationError,
) -> bool:
    if error.validator != "uniqueItems":
        return False
    path = tuple(error.absolute_path)
    return path == ("nodes",) or path == ("edges",) or (
        len(path) == 3
        and path[0] == "nodes"
        and isinstance(path[1], int)
        and path[2] == "parameterBindings"
    )


def _plan_schema_error_details(error: jsonschema.ValidationError):
    if error.validator in ("oneOf", "anyOf") and error.context:
        details = []
        for child in sorted(
            error.context,
            key=lambda item: (
                tuple(str(part) for part in item.absolute_path),
                str(item.validator),
                item.message,
            ),
        ):
            details.extend(_plan_schema_error_details(child))
        return tuple(details)
    return _schema_error_details(error)


def _validate_plan_stable_ids(
    plan_graph: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    for collection_name, id_field in (("nodes", "nodeId"), ("edges", "edgeId")):
        seen: set[str] = set()
        values = plan_graph.get(collection_name)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if not isinstance(value, Mapping):
                continue
            item_id = value.get(id_field)
            if not isinstance(item_id, str):
                continue
            if item_id in seen:
                issues.append(
                    ValidationIssue(
                        f"/{collection_name}/{index}/{id_field}",
                        "DUPLICATE_ID",
                        f"duplicate {id_field}: {item_id}",
                    )
                )
            else:
                seen.add(item_id)


def _validate_snapshot_and_goal_identity(
    snapshot: RegistrySnapshot,
    goal_spec: Mapping[str, Any],
    plan_graph: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    if plan_graph["snapshotId"] != snapshot.snapshot_id:
        issues.append(
            ValidationIssue(
                "/snapshotId",
                "SNAPSHOT_MISMATCH",
                "plan snapshotId does not match RegistrySnapshot",
            )
        )
    for field in ("goalId", "executionMode"):
        if plan_graph[field] != goal_spec.get(field):
            issues.append(
                ValidationIssue(
                    f"/{field}",
                    "PLAN_PROJECTION_MISMATCH",
                    f"plan {field} does not match GoalSpec",
                )
            )


def _validate_nodes_and_projections(
    graph: ImmutableSemanticGraph,
    plan_graph: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> dict[str, tuple[int, Mapping[str, Any], Mapping[str, Any]]]:
    node_index: dict[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ] = {}
    for index, node in enumerate(plan_graph["nodes"]):
        node_id = node["nodeId"]
        capability_id = node["capabilityId"]
        capability = graph.capabilities.get(capability_id)
        if capability is None:
            issues.append(
                ValidationIssue(
                    f"/nodes/{index}/capabilityId",
                    "UNKNOWN_CAPABILITY",
                    f"capability is not registered: {capability_id}",
                )
            )
            continue
        node_index[node_id] = (index, node, capability)

        expected_facts = sorted(
            {
                output["factTypeRef"]
                for output in capability["outputs"]
                if "factTypeRef" in output
            }
        )
        if sorted(node["producesFactTypes"]) != expected_facts:
            issues.append(
                ValidationIssue(
                    f"/nodes/{index}/producesFactTypes",
                    "PLAN_PROJECTION_MISMATCH",
                    "producesFactTypes does not match Registry projection",
                )
            )

        governance = capability["governance"]
        expected_governance = {
            "capabilityKind": capability["kind"],
            "sideEffect": governance["sideEffect"],
            "requiresApproval": governance["requiresApproval"],
            "approvalPolicy": governance["approvalPolicy"],
        }
        if node["governance"] != expected_governance:
            issues.append(
                ValidationIssue(
                    f"/nodes/{index}/governance",
                    "PLAN_PROJECTION_MISMATCH",
                    "governance does not match Registry projection",
                )
            )
    return node_index


def _validate_parameter_sources(
    graph: ImmutableSemanticGraph,
    goal_spec: Mapping[str, Any],
    node_index: Mapping[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ],
    issues: list[ValidationIssue],
) -> None:
    del graph
    constraints = {
        constraint["name"]: constraint
        for constraint in goal_spec.get("constraints", ())
        if isinstance(constraint, Mapping)
    }
    for node_id in sorted(node_index):
        node_index_value, node, capability = node_index[node_id]
        inputs = {item["name"]: item for item in capability["inputs"]}
        bindings: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
        for binding_index, binding in enumerate(node["parameterBindings"]):
            parameter_name = binding["parameterName"]
            input_field = inputs.get(parameter_name)
            if input_field is None:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_index_value}/parameterBindings/{binding_index}/parameterName",
                        "PLAN_PROJECTION_MISMATCH",
                        f"parameter is not registered: {parameter_name}",
                    )
                )
                continue
            bindings[parameter_name].append((binding_index, binding))

        for parameter_name, input_field in inputs.items():
            matches = bindings.get(parameter_name, [])
            if input_field["required"] and not matches:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_index_value}/parameterBindings",
                        "PARAMETER_SOURCE_MISSING",
                        f"required parameter has no source: {parameter_name}",
                    )
                )
            for duplicate_index, _ in matches[1:]:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_index_value}/parameterBindings/{duplicate_index}/parameterName",
                        "PARAMETER_SOURCE_DUPLICATE",
                        f"parameter has multiple sources: {parameter_name}",
                    )
                )
            if len(matches) == 1:
                binding_index, binding = matches[0]
                _validate_parameter_source(
                    node_index_value,
                    binding_index,
                    input_field,
                    binding["source"],
                    constraints,
                    node_index,
                    issues,
                )


def _validate_parameter_source(
    node_index_value: int,
    binding_index: int,
    input_field: Mapping[str, Any],
    source: Mapping[str, Any],
    constraints: Mapping[str, Mapping[str, Any]],
    node_index: Mapping[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ],
    issues: list[ValidationIssue],
) -> None:
    base_path = (
        f"/nodes/{node_index_value}/parameterBindings/{binding_index}/source"
    )
    source_kind = source["kind"]
    if source_kind == "goalConstraint":
        constraint = constraints.get(source["constraintName"])
        if (
            input_field["bindingKind"] != "identifier"
            or constraint is None
            or constraint["semanticType"] != input_field["semanticType"]
        ):
            issues.append(
                ValidationIssue(
                    f"{base_path}/constraintName",
                    "PARAMETER_SOURCE_MISSING",
                    "goal constraint cannot satisfy parameter semantic type",
                )
            )
        return

    if source_kind == "literal":
        if (
            input_field["bindingKind"] != "identifier"
            or source["semanticType"] != input_field["semanticType"]
        ):
            issues.append(
                ValidationIssue(
                    f"{base_path}/semanticType",
                    "PARAMETER_SOURCE_MISSING",
                    "literal cannot satisfy parameter semantic type",
                )
            )
        return

    producer = node_index.get(source["producerNodeId"])
    expected_fact_type = input_field.get("satisfiableByFactType")
    if not expected_fact_type or source["factTypeId"] != expected_fact_type:
        issues.append(
            ValidationIssue(
                f"{base_path}/factTypeId",
                "FACT_TYPE_MISMATCH",
                "fact source cannot satisfy parameter Fact Type",
            )
        )
        return
    if producer is None:
        issues.append(
            ValidationIssue(
                f"{base_path}/producerNodeId",
                "FACT_TYPE_MISMATCH",
                "fact producer node is not valid",
            )
        )
        return
    producer_capability = producer[2]
    output_matches = any(
        output["name"] == source["field"]
        and output.get("factTypeRef") == source["factTypeId"]
        for output in producer_capability["outputs"]
    )
    if not output_matches:
        issues.append(
            ValidationIssue(
                f"{base_path}/field",
                "FACT_TYPE_MISMATCH",
                "field is not published for the declared producer Fact Type",
            )
        )


def _validate_edges(
    graph: ImmutableSemanticGraph,
    node_index: Mapping[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ],
    plan_graph: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    expected_data: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for consumer_node_id, (node_position, node, _) in node_index.items():
        for binding_index, binding in enumerate(node["parameterBindings"]):
            source = binding["source"]
            if source["kind"] != "factField":
                continue
            key = (
                source["producerNodeId"],
                consumer_node_id,
                source["factTypeId"],
            )
            expected_data[key].append(
                f"/nodes/{node_position}/parameterBindings/{binding_index}/source"
            )

    data_edges: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    dependency_edges: dict[tuple[str, str], list[int]] = defaultdict(list)
    for edge_index, edge in enumerate(plan_graph["edges"]):
        if edge["kind"] == "data":
            data_edges[
                (edge["fromNodeId"], edge["toNodeId"], edge["factTypeId"])
            ].append(edge_index)
        else:
            dependency_edges[
                (edge["fromNodeId"], edge["toNodeId"])
            ].append(edge_index)

    for key, source_paths in expected_data.items():
        edge_indexes = data_edges.get(key, [])
        if not edge_indexes:
            for source_path in source_paths:
                issues.append(
                    ValidationIssue(
                        source_path,
                        "EDGE_INCONSISTENT",
                        "factField source must have exactly one matching data edge",
                    )
                )
    for key, edge_indexes in data_edges.items():
        if key not in expected_data:
            for edge_index in edge_indexes:
                issues.append(
                    ValidationIssue(
                        f"/edges/{edge_index}",
                        "EDGE_INCONSISTENT",
                        "data edge must have at least one matching factField source",
                    )
                )
            continue
        for edge_index in edge_indexes[1:]:
            issues.append(
                ValidationIssue(
                    f"/edges/{edge_index}",
                    "EDGE_INCONSISTENT",
                    "duplicate semantic data edge",
                )
            )

    expected_dependencies: set[tuple[str, str]] = set()
    nodes_by_capability: dict[str, list[str]] = defaultdict(list)
    for node_id, (_, _, capability) in node_index.items():
        nodes_by_capability[capability["capabilityId"]].append(node_id)
    for semantic_edge in graph.edges:
        if semantic_edge.relation_type != "dependsOn":
            continue
        dependents = nodes_by_capability.get(semantic_edge.source_id, ())
        prerequisites = nodes_by_capability.get(semantic_edge.target_id, ())
        if dependents and not prerequisites:
            issues.append(
                ValidationIssue(
                    "/edges",
                    "EDGE_INCONSISTENT",
                    "authored dependency prerequisite is absent: "
                    f"{semantic_edge.target_id}",
                )
            )
        for dependent in dependents:
            for prerequisite in prerequisites:
                expected_dependencies.add((prerequisite, dependent))

    for dependency in sorted(expected_dependencies):
        if len(dependency_edges.get(dependency, ())) != 1:
            issues.append(
                ValidationIssue(
                    "/edges",
                    "EDGE_INCONSISTENT",
                    "authored dependency requires one prerequisite-to-dependent edge",
                )
            )
    for dependency, edge_indexes in dependency_edges.items():
        if dependency not in expected_dependencies or len(edge_indexes) != 1:
            for edge_index in edge_indexes:
                issues.append(
                    ValidationIssue(
                        f"/edges/{edge_index}",
                        "EDGE_INCONSISTENT",
                        "dependency edge does not match authored dependsOn relation",
                    )
                )

    _validate_plan_edge_cycles(plan_graph, node_index, issues)


def _validate_plan_edge_cycles(
    plan_graph: Mapping[str, Any],
    node_index: Mapping[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ],
    issues: list[ValidationIssue],
) -> None:
    adjacency: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for edge_index, edge in enumerate(plan_graph["edges"]):
        source = edge["fromNodeId"]
        target = edge["toNodeId"]
        if source in node_index and target in node_index:
            adjacency[source].append((target, edge_index))

    states: dict[str, int] = {}
    path: list[str] = []
    positions: dict[str, int] = {}

    for node_id in sorted(node_index):
        if states.get(node_id, 0) != 0:
            continue
        states[node_id] = 1
        positions[node_id] = len(path)
        path.append(node_id)
        frames = [(node_id, tuple(sorted(adjacency.get(node_id, ()))), 0)]
        while frames:
            current, outgoing, cursor = frames[-1]
            if cursor >= len(outgoing):
                frames.pop()
                path.pop()
                positions.pop(current)
                states[current] = 2
                continue
            target, edge_index = outgoing[cursor]
            frames[-1] = (current, outgoing, cursor + 1)
            if states.get(target, 0) == 0:
                states[target] = 1
                positions[target] = len(path)
                path.append(target)
                frames.append(
                    (target, tuple(sorted(adjacency.get(target, ()))), 0)
                )
            elif states.get(target) == 1:
                cycle = path[positions[target] :] + [target]
                issues.append(
                    ValidationIssue(
                        f"/edges/{edge_index}/toNodeId",
                        "DEPENDENCY_CYCLE",
                        f"plan edge cycle detected: {' -> '.join(cycle)}",
                    )
                )


def _validate_topological_order(
    node_index: Mapping[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ],
    plan_graph: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    order = plan_graph["topologicalOrder"]
    if len(order) != len(node_index) or set(order) != set(node_index):
        issues.append(
            ValidationIssue(
                "/topologicalOrder",
                "PLAN_PROJECTION_MISMATCH",
                "topologicalOrder must cover every valid plan node exactly once",
            )
        )
        return
    positions = {node_id: index for index, node_id in enumerate(order)}
    if any(
        positions.get(edge["fromNodeId"], len(order))
        >= positions.get(edge["toNodeId"], -1)
        for edge in plan_graph["edges"]
    ):
        issues.append(
            ValidationIssue(
                "/topologicalOrder",
                "EDGE_INCONSISTENT",
                "topologicalOrder violates a plan edge direction",
            )
        )


def _validate_plan_governance(
    goal_spec: Mapping[str, Any],
    node_index: Mapping[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ],
    issues: list[ValidationIssue],
) -> None:
    if goal_spec.get("executionMode") != "READ_ONLY":
        return
    for node_id in sorted(node_index):
        node_position, _, capability = node_index[node_id]
        if not _is_read_only(capability):
            issues.append(
                ValidationIssue(
                    f"/nodes/{node_position}/governance",
                    "GOVERNANCE_VIOLATION",
                    "READ_ONLY plan contains a non-read-only capability",
                )
            )


def _validate_goal_outputs(
    goal_spec: Mapping[str, Any],
    node_index: Mapping[
        str, tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ],
    plan_graph: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    desired = set(goal_spec.get("desiredFactTypes", ()))
    outputs_by_fact: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    for output_index, output in enumerate(plan_graph["goalOutputs"]):
        outputs_by_fact[output["factTypeId"]].append((output_index, output))
        if output["factTypeId"] not in desired:
            issues.append(
                ValidationIssue(
                    f"/goalOutputs/{output_index}/factTypeId",
                    "GOAL_OUTPUT_UNSATISFIED",
                    "goal output is not requested by GoalSpec",
                )
            )

    for fact_type_id in sorted(desired):
        matches = outputs_by_fact.get(fact_type_id, [])
        if len(matches) != 1:
            issues.append(
                ValidationIssue(
                    "/goalOutputs",
                    "GOAL_OUTPUT_UNSATISFIED",
                    f"desired Fact Type requires exactly one producer: {fact_type_id}",
                )
            )
            continue
        output_index, output = matches[0]
        producer = node_index.get(output["producerNodeId"])
        if producer is None or fact_type_id not in producer[1]["producesFactTypes"]:
            issues.append(
                ValidationIssue(
                    f"/goalOutputs/{output_index}/producerNodeId",
                    "GOAL_OUTPUT_UNSATISFIED",
                    "producer node does not project the desired Fact Type",
                )
            )


def _is_read_only(capability: Mapping[str, Any]) -> bool:
    governance = capability["governance"]
    return (
        capability["kind"] == "Function"
        and governance["sideEffect"] == "none"
        and governance["requiresApproval"] is False
        and governance["approvalPolicy"] == "not_required"
    )


def _validate_goal_shape(
    goal_spec: Any,
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    conversion_candidates: list[tuple[str, ValidationIssue]] = []
    normalized = _to_json_value(
        goal_spec,
        (),
        "",
        "__goal__",
        "",
        conversion_candidates,
    )
    conversion_issues = [issue for _, issue in conversion_candidates]
    conversion_paths = {issue.path for issue in conversion_issues}
    issues.extend(conversion_issues)

    validator = jsonschema.Draft202012Validator(
        _load_schema("goal-spec.schema.json")
    )
    errors = sorted(
        validator.iter_errors(normalized),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
            error.message,
        ),
    )
    for error in errors:
        if _unique_items_is_conversion_artifact(error, conversion_paths):
            continue
        for tokens, message in _schema_error_details(error):
            path = "".join(f"/{_pointer_token(token)}" for token in tokens)
            if error.instance is None and path in conversion_paths:
                continue
            issues.append(
                ValidationIssue(
                    path=path,
                    code="SCHEMA_INVALID",
                    message=message,
                )
            )

    if isinstance(normalized, dict) and isinstance(
        normalized.get("constraints"), list
    ):
        seen_names: set[str] = set()
        for index, constraint in enumerate(normalized["constraints"]):
            if not isinstance(constraint, dict):
                continue
            name = constraint.get("name")
            if not isinstance(name, str):
                continue
            if name in seen_names:
                issues.append(
                    ValidationIssue(
                        path=f"/constraints/{index}/name",
                        code="SCHEMA_INVALID",
                        message=f"duplicate constraint name: {name}",
                    )
                )
            else:
                seen_names.add(name)

    return normalized if isinstance(normalized, dict) else {}


def _unique_items_is_conversion_artifact(
    error: jsonschema.ValidationError,
    conversion_paths: set[str],
) -> bool:
    if error.validator != "uniqueItems" or not isinstance(error.instance, list):
        return False

    base_path = "".join(
        f"/{_pointer_token(token)}" for token in error.absolute_path
    )
    converted_items = tuple(
        any(
            path == f"{base_path}/{index}"
            or path.startswith(f"{base_path}/{index}/")
            for path in conversion_paths
        )
        for index in range(len(error.instance))
    )
    duplicate_found = False
    for index, value in enumerate(error.instance):
        for previous_index in range(index):
            previous_value = error.instance[previous_index]
            if not _json_instances_equal(value, previous_value):
                continue
            duplicate_found = True
            if not converted_items[index] and not converted_items[previous_index]:
                return False
    return duplicate_found


def _json_instances_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right

    left_is_number = isinstance(left, (int, float))
    right_is_number = isinstance(right, (int, float))
    if left_is_number or right_is_number:
        return left_is_number and right_is_number and left == right

    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        return len(left) == len(right) and all(
            key in right and _json_instances_equal(left[key], right[key])
            for key in left
        )

    if isinstance(left, list) or isinstance(right, list):
        if not isinstance(left, list) or not isinstance(right, list):
            return False
        return len(left) == len(right) and all(
            _json_instances_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )

    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    return False


def _canonical_issues(
    issues: list[ValidationIssue],
) -> tuple[ValidationIssue, ...]:
    selected = {
        (issue.path, issue.code, issue.message): issue for issue in issues
    }
    return sorted_issues(list(selected.values()))


def _invalid_result(issues: list[ValidationIssue]) -> ContractBuildResult:
    return ContractBuildResult(
        report=ContractValidationReport(
            valid=False,
            issues=_canonical_issues(issues),
        ),
        graph=None,
        snapshot=None,
    )


_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"
_MAX_JSON_CONTAINER_DEPTH = 64


@lru_cache(maxsize=None)
def _load_schema(schema_name: str) -> dict[str, Any]:
    return json.loads((_SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))


def _validate_source_schemas(
    sources: SemanticSourceDocuments,
    issues: list[ValidationIssue],
) -> tuple[ValidationIssue, ...]:
    documents = (
        (
            sources.capabilities,
            "capability.schema.json",
            "capabilities",
            "/capabilityRegistry",
            "/capabilities",
            2,
        ),
        (
            sources.executor_bindings,
            "executor-binding.schema.json",
            "bindings",
            "/executorBindingCatalog",
            "/bindings",
            1,
        ),
        (
            sources.fact_types,
            "fact-type-catalog.schema.json",
            "factTypes",
            "/factTypeCatalog",
            "/factTypes",
            2,
        ),
        (
            sources.relations,
            "capability-relation.schema.json",
            "relations",
            "/capabilityRelationCatalog",
            "/relations",
            1,
        ),
    )
    candidates: list[tuple[str, ValidationIssue]] = []
    for (
        document,
        schema_name,
        collection_name,
        source_path,
        collection_path,
        expected_version,
    ) in documents:
        json_document = _to_json_value(
            document,
            (),
            source_path,
            collection_name,
            collection_path,
            candidates,
        )
        validator = jsonschema.Draft202012Validator(_load_schema(schema_name))
        errors = sorted(
            validator.iter_errors(json_document),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                str(error.validator),
                error.message,
            ),
        )
        for error in errors:
            if (
                error.validator == "uniqueItems"
                and tuple(error.absolute_path) == (collection_name,)
            ):
                duplicate_issues, fully_reconciled = _collection_duplicate_issues(
                    collection_name, collection_path, error.instance
                )
                candidates.extend(
                    ("semantic_duplicate", issue) for issue in duplicate_issues
                )
                if fully_reconciled:
                    continue
            for tokens, message in _schema_error_details(error):
                path = _source_path(
                    tokens,
                    source_path,
                    collection_name,
                    collection_path,
                )
                if error.instance is None:
                    origin = "schema_placeholder"
                elif error.validator == "type" and path.endswith(
                    ("/satisfiableByFactType", "/factTypeRef")
                ):
                    origin = "fact_reference_type"
                elif error.validator == "not" and path.endswith(
                    "/satisfiableByFactType"
                ):
                    origin = "fact_reference_forbidden"
                else:
                    origin = "schema"
                candidates.append(
                    (
                        origin,
                        ValidationIssue(
                            path=path,
                            code="SCHEMA_INVALID",
                            message=message,
                        ),
                    )
                )

        version = (
            json_document.get("version")
            if isinstance(json_document, dict)
            else None
        )
        if type(version) is int and version != expected_version:
            candidates.append(
                (
                    "supplemental_version",
                    ValidationIssue(
                        path=f"{source_path}/version",
                        code="SCHEMA_INVALID",
                        message=f"version must be {expected_version}",
                    ),
                )
            )

    conversion_paths = {
        issue.path for origin, issue in candidates if origin == "conversion"
    }
    schema_paths = {
        issue.path for origin, issue in candidates if origin == "schema"
    }
    fact_reference_type_paths = {
        issue.path
        for origin, issue in candidates
        if origin == "fact_reference_type"
    }
    selected: dict[
        tuple[str, str, str],
        tuple[str, ValidationIssue],
    ] = {}
    for origin, issue in candidates:
        if origin == "schema_placeholder" and issue.path in conversion_paths:
            continue
        if origin == "supplemental_version" and issue.path in schema_paths:
            continue
        if (
            origin == "fact_reference_forbidden"
            and issue.path in fact_reference_type_paths
        ):
            continue
        selected.setdefault(
            (issue.path, issue.code, issue.message),
            (origin, issue),
        )
    issues.extend(
        issue
        for origin, issue in selected.values()
        if origin != "semantic_duplicate"
    )
    return tuple(
        issue
        for origin, issue in selected.values()
        if origin == "semantic_duplicate"
    )


def _collection_duplicate_issues(
    collection_name: str,
    collection_path: str,
    values: Any,
) -> tuple[tuple[ValidationIssue, ...], bool]:
    if collection_name not in ("factTypes", "relations") or not isinstance(
        values, list
    ):
        return (), False

    seen: set[str] = set()
    duplicate_count = 0
    reconciled_count = 0
    issues: list[ValidationIssue] = []
    for index, value in enumerate(values):
        fingerprint = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        if fingerprint not in seen:
            seen.add(fingerprint)
            continue
        duplicate_count += 1
        if not isinstance(value, Mapping):
            continue
        if collection_name == "factTypes":
            item_id = value.get("factTypeId")
            if not isinstance(item_id, str) or not item_id:
                continue
            issues.append(
                ValidationIssue(
                    path=f"{collection_path}/{index}/factTypeId",
                    code="DUPLICATE_ID",
                    message=f"duplicate factTypeId: {item_id}",
                )
            )
            reconciled_count += 1
            continue

        relation_id = value.get("relationId")
        relation_type = value.get("relationType")
        capability_id = value.get("capabilityId")
        target_field = (
            "dependsOnCapabilityId"
            if relation_type == "dependsOn"
            else "requiredFactType"
            if relation_type == "precondition"
            else None
        )
        target = value.get(target_field) if target_field else None
        if not all(
            isinstance(item, str) and item
            for item in (relation_id, capability_id, target)
        ):
            continue
        edge = (relation_type, capability_id, target)
        issues.extend(
            (
                ValidationIssue(
                    path=f"{collection_path}/{index}",
                    code="DUPLICATE_ID",
                    message=f"duplicate authored semantic edge: {edge!r}",
                ),
                ValidationIssue(
                    path=f"{collection_path}/{index}/relationId",
                    code="DUPLICATE_ID",
                    message=f"duplicate relationId: {relation_id}",
                ),
            )
        )
        reconciled_count += 1

    return tuple(issues), duplicate_count > 0 and duplicate_count == reconciled_count


def _to_json_value(
    value: Any,
    tokens: tuple[Any, ...],
    source_path: str,
    collection_name: str,
    collection_path: str,
    candidates: list[tuple[str, ValidationIssue]],
    active_container_ids: set[int] | None = None,
    container_depth: int = 0,
) -> Any:
    if isinstance(value, (Mapping, list, tuple)):
        if container_depth >= _MAX_JSON_CONTAINER_DEPTH:
            candidates.append(
                (
                    "conversion",
                    ValidationIssue(
                        path=_source_path(
                            tokens,
                            source_path,
                            collection_name,
                            collection_path,
                        ),
                        code="SCHEMA_INVALID",
                        message="JSON container nesting exceeds safe depth",
                    ),
                )
            )
            return None
        if active_container_ids is None:
            active_container_ids = set()
        identity = id(value)
        if identity in active_container_ids:
            candidates.append(
                (
                    "conversion",
                    ValidationIssue(
                        path=_source_path(
                            tokens,
                            source_path,
                            collection_name,
                            collection_path,
                        ),
                        code="SCHEMA_INVALID",
                        message="recursive JSON container",
                    ),
                )
            )
            return None
        active_container_ids.add(identity)
        try:
            return _to_json_container(
                value,
                tokens,
                source_path,
                collection_name,
                collection_path,
                candidates,
                active_container_ids,
                container_depth,
            )
        finally:
            active_container_ids.remove(identity)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    candidates.append(
        (
            "conversion",
            ValidationIssue(
                path=_source_path(
                    tokens, source_path, collection_name, collection_path
                ),
                code="SCHEMA_INVALID",
                message=f"unsupported JSON value: {type(value).__name__}",
            ),
        )
    )
    return None


def _to_json_container(
    value: Mapping[Any, Any] | list[Any] | tuple[Any, ...],
    tokens: tuple[Any, ...],
    source_path: str,
    collection_name: str,
    collection_path: str,
    candidates: list[tuple[str, ValidationIssue]],
    active_container_ids: set[int],
    container_depth: int,
) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                candidates.append(
                    (
                        "conversion",
                        ValidationIssue(
                            path=_source_path(
                                tokens,
                                source_path,
                                collection_name,
                                collection_path,
                            ),
                            code="SCHEMA_INVALID",
                            message="mapping keys must be strings",
                        ),
                    )
                )
                continue
            result[key] = _to_json_value(
                item,
                (*tokens, key),
                source_path,
                collection_name,
                collection_path,
                candidates,
                active_container_ids,
                container_depth + 1,
            )
        return result
    return [
        _to_json_value(
            item,
            (*tokens, index),
            source_path,
            collection_name,
            collection_path,
            candidates,
            active_container_ids,
            container_depth + 1,
        )
        for index, item in enumerate(value)
    ]


def _schema_error_details(error: jsonschema.ValidationError):
    tokens = tuple(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = sorted(
            field for field in error.validator_value if field not in error.instance
        )
        return tuple(((*tokens, field), f"{field} is required") for field in missing)
    if error.validator == "additionalProperties" and isinstance(
        error.instance, dict
    ):
        known = set(error.schema.get("properties", ()))
        extras = sorted(key for key in error.instance if key not in known)
        return tuple(
            ((*tokens, field), f"unexpected property: {field}") for field in extras
        )
    if (
        error.validator == "not"
        and isinstance(error.instance, dict)
        and isinstance(error.schema.get("not"), dict)
    ):
        forbidden = error.schema["not"].get("required")
        if isinstance(forbidden, list):
            return tuple(
                ((*tokens, field), f"property is not allowed: {field}")
                for field in sorted(forbidden)
            )
    return ((tokens, error.message),)


def _source_path(
    tokens: tuple[Any, ...],
    source_path: str,
    collection_name: str,
    collection_path: str,
) -> str:
    if tokens and tokens[0] == collection_name:
        base = collection_path
        tokens = tokens[1:]
    else:
        base = source_path
    if not tokens:
        return base
    return base + "".join(f"/{_pointer_token(token)}" for token in tokens)


def _pointer_token(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _validate_executor_bindings(
    sources: SemanticSourceDocuments,
    issues: list[ValidationIssue],
) -> None:
    bindings = {
        binding.get("bindingId"): binding
        for binding in _items(sources.executor_bindings, "bindings")
        if isinstance(binding, Mapping)
        and isinstance(binding.get("bindingId"), str)
        and binding.get("bindingId")
    }
    for index, capability in enumerate(_items(sources.capabilities, "capabilities")):
        if not isinstance(capability, Mapping):
            continue
        executor = capability.get("executorBinding")
        if not isinstance(executor, Mapping):
            continue
        binding_id = executor.get("bindingId")
        binding_path = f"/capabilities/{index}/executorBinding/bindingId"
        if not isinstance(binding_id, str) or binding_id not in bindings:
            _add_issue(
                issues,
                binding_path,
                "SCHEMA_INVALID",
                f"executor binding not found: {binding_id!r}",
            )
            continue
        if executor.get("type") != bindings[binding_id].get("type"):
            _add_issue(
                issues,
                f"/capabilities/{index}/executorBinding/type",
                "SCHEMA_INVALID",
                "executor binding type does not match binding catalog",
            )


def _validate_unique_ids(
    sources: SemanticSourceDocuments,
    issues: list[ValidationIssue],
) -> None:
    catalogs = (
        (_items(sources.capabilities, "capabilities"), "capabilityId", "/capabilities"),
        (_items(sources.fact_types, "factTypes"), "factTypeId", "/factTypes"),
        (_items(sources.relations, "relations"), "relationId", "/relations"),
        (_items(sources.executor_bindings, "bindings"), "bindingId", "/bindings"),
    )
    for values, id_field, base_path in catalogs:
        seen: dict[str, int] = {}
        for index, value in enumerate(values):
            if not isinstance(value, Mapping):
                continue
            item_id = value.get(id_field)
            path = f"{base_path}/{index}/{id_field}"
            if not isinstance(item_id, str) or not item_id:
                _add_issue(
                    issues, path, "SCHEMA_INVALID", f"{id_field} is required"
                )
            elif item_id in seen:
                _add_issue(
                    issues,
                    path,
                    "DUPLICATE_ID",
                    f"duplicate {id_field}: {item_id}",
                )
            else:
                seen[item_id] = index


def _validate_fact_references(
    sources: SemanticSourceDocuments,
    issues: list[ValidationIssue],
) -> None:
    fact_type_ids = {
        fact_type.get("factTypeId")
        for fact_type in _items(sources.fact_types, "factTypes")
        if isinstance(fact_type, Mapping)
        and isinstance(fact_type.get("factTypeId"), str)
        and fact_type.get("factTypeId")
    }
    for capability_index, capability in enumerate(
        _items(sources.capabilities, "capabilities")
    ):
        if not isinstance(capability, Mapping):
            continue
        for input_index, input_field in enumerate(capability.get("inputs") or ()):
            if not isinstance(input_field, Mapping):
                continue
            base_path = f"/capabilities/{capability_index}/inputs/{input_index}"
            binding_kind = input_field.get("bindingKind")
            fact_type_ref = input_field.get("satisfiableByFactType")
            if binding_kind not in ("identifier", "fact"):
                _add_issue(
                    issues,
                    f"{base_path}/bindingKind",
                    "SCHEMA_INVALID",
                    "bindingKind must be identifier or fact",
                )
            elif binding_kind == "fact" and not fact_type_ref:
                _add_issue(
                    issues,
                    f"{base_path}/satisfiableByFactType",
                    "SCHEMA_INVALID",
                    "fact input requires satisfiableByFactType",
                )
            if fact_type_ref is not None and not isinstance(fact_type_ref, str):
                _add_issue(
                    issues,
                    f"{base_path}/satisfiableByFactType",
                    "SCHEMA_INVALID",
                    "satisfiableByFactType must be a string",
                )
            elif fact_type_ref and fact_type_ref not in fact_type_ids:
                _add_issue(
                    issues,
                    f"{base_path}/satisfiableByFactType",
                    "UNKNOWN_FACT_TYPE",
                    f"unknown Fact Type: {fact_type_ref}",
                )
        for output_index, output in enumerate(capability.get("outputs") or ()):
            if not isinstance(output, Mapping):
                continue
            base_path = f"/capabilities/{capability_index}/outputs/{output_index}"
            fact_type_ref = output.get("factTypeRef")
            if output.get("evidenceRole") == "primaryFact" and not fact_type_ref:
                _add_issue(
                    issues,
                    f"{base_path}/factTypeRef",
                    "SCHEMA_INVALID",
                    "primaryFact output requires factTypeRef",
                )
            if fact_type_ref is not None and not isinstance(fact_type_ref, str):
                _add_issue(
                    issues,
                    f"{base_path}/factTypeRef",
                    "SCHEMA_INVALID",
                    "factTypeRef must be a string",
                )
            elif fact_type_ref and fact_type_ref not in fact_type_ids:
                _add_issue(
                    issues,
                    f"{base_path}/factTypeRef",
                    "UNKNOWN_FACT_TYPE",
                    f"unknown Fact Type: {fact_type_ref}",
                )


def _semantic_types_declared_by_capabilities(
    sources: SemanticSourceDocuments,
) -> set[str]:
    """The ontology vocabulary, as declared by capability inputs and outputs.

    Fact Type field semantic types are drawn from this set (design Decision 1),
    which is what keeps ``registry/semantic-types.yaml`` — the extraction
    matcher catalog, with its bare ids — from being mistaken for the authority.
    """
    declared: set[str] = set()
    for capability in _items(sources.capabilities, "capabilities"):
        if not isinstance(capability, Mapping):
            continue
        for container in ("inputs", "outputs"):
            for field in capability.get(container) or ():
                if isinstance(field, Mapping) and isinstance(
                    field.get("semanticType"), str
                ):
                    declared.add(field["semanticType"])
    return declared


def _validate_fact_type_fields(
    sources: SemanticSourceDocuments,
    issues: list[ValidationIssue],
) -> None:
    """Fact Type field lists are the authority data dependency edges derive from.

    Two rules:

    * the field's ``semanticType`` must exist in the ontology vocabulary;
    * a ``cardinality: one`` field must be published as a same-named,
      same-``semanticType`` output by at least one active producer of that Fact
      Type. ``cardinality: many`` fields are exempt — they describe items inside
      an array payload whose container output name is deliberately not declared
      as a field.
    """
    declared_semantic_types = _semantic_types_declared_by_capabilities(sources)
    published: set[tuple[str, str, str]] = set()
    for capability in _items(sources.capabilities, "capabilities"):
        if not isinstance(capability, Mapping) or capability.get("status") != "active":
            continue
        for output in capability.get("outputs") or ():
            if not isinstance(output, Mapping):
                continue
            fact_type_ref = output.get("factTypeRef")
            name = output.get("name")
            semantic_type = output.get("semanticType")
            if (
                isinstance(fact_type_ref, str)
                and isinstance(name, str)
                and isinstance(semantic_type, str)
            ):
                published.add((fact_type_ref, name, semantic_type))

    for fact_index, fact_type in enumerate(_items(sources.fact_types, "factTypes")):
        if not isinstance(fact_type, Mapping):
            continue
        fact_type_id = fact_type.get("factTypeId")
        for field_index, field in enumerate(fact_type.get("fields") or ()):
            if not isinstance(field, Mapping):
                continue
            base_path = f"/factTypes/{fact_index}/fields/{field_index}"
            name = field.get("name")
            semantic_type = field.get("semanticType")
            if semantic_type not in declared_semantic_types:
                _add_issue(
                    issues,
                    f"{base_path}/semanticType",
                    "UNKNOWN_SEMANTIC_TYPE",
                    f"{fact_type_id}.{name}: unknown semantic type: {semantic_type}",
                )
            elif (
                field.get("cardinality") == "one"
                and (fact_type_id, name, semantic_type) not in published
            ):
                _add_issue(
                    issues,
                    f"{base_path}/name",
                    "UNPUBLISHED_FACT_FIELD",
                    f"{fact_type_id}.{name}: no active producer publishes an "
                    f"output named {name} with semantic type {semantic_type}",
                )


def _validate_relation_endpoints(
    sources: SemanticSourceDocuments,
    issues: list[ValidationIssue],
) -> None:
    capability_ids = {
        capability.get("capabilityId")
        for capability in _items(sources.capabilities, "capabilities")
        if isinstance(capability, Mapping)
        and isinstance(capability.get("capabilityId"), str)
        and capability.get("capabilityId")
    }
    fact_type_ids = {
        fact_type.get("factTypeId")
        for fact_type in _items(sources.fact_types, "factTypes")
        if isinstance(fact_type, Mapping)
        and isinstance(fact_type.get("factTypeId"), str)
        and fact_type.get("factTypeId")
    }
    seen_edges: set[tuple[Any, Any, Any]] = set()
    for index, relation in enumerate(_items(sources.relations, "relations")):
        if not isinstance(relation, Mapping):
            continue
        base_path = f"/relations/{index}"
        relation_type = relation.get("relationType")
        capability_id = relation.get("capabilityId")
        if relation_type not in ("dependsOn", "precondition"):
            _add_issue(
                issues,
                f"{base_path}/relationType",
                "SCHEMA_INVALID",
                "authored relationType must be dependsOn or precondition",
            )
            continue
        if not isinstance(capability_id, str) or capability_id not in capability_ids:
            _add_issue(
                issues,
                f"{base_path}/capabilityId",
                "RELATION_ENDPOINT_NOT_FOUND",
                f"capability endpoint not found: {capability_id!r}",
            )
        if relation_type == "dependsOn":
            target_field = "dependsOnCapabilityId"
            target = relation.get(target_field)
            target_exists = isinstance(target, str) and target in capability_ids
        else:
            target_field = "requiredFactType"
            target = relation.get(target_field)
            target_exists = isinstance(target, str) and target in fact_type_ids
        if not target_exists:
            _add_issue(
                issues,
                f"{base_path}/{target_field}",
                "RELATION_ENDPOINT_NOT_FOUND",
                f"relation endpoint not found: {target!r}",
            )
        if isinstance(capability_id, str) and isinstance(target, str):
            edge = (relation_type, capability_id, target)
            if edge in seen_edges:
                _add_issue(
                    issues,
                    base_path,
                    "DUPLICATE_ID",
                    f"duplicate authored semantic edge: {edge!r}",
                )
            else:
                seen_edges.add(edge)


def _validate_dependency_cycles(
    sources: SemanticSourceDocuments,
    issues: list[ValidationIssue],
) -> None:
    capability_ids = {
        capability.get("capabilityId")
        for capability in _items(sources.capabilities, "capabilities")
        if isinstance(capability, Mapping)
        and isinstance(capability.get("capabilityId"), str)
        and capability.get("capabilityId")
    }
    dependencies: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for index, relation in enumerate(_items(sources.relations, "relations")):
        if not isinstance(relation, Mapping) or relation.get("relationType") != "dependsOn":
            continue
        source = relation.get("capabilityId")
        target = relation.get("dependsOnCapabilityId")
        if (
            not isinstance(source, str)
            or not isinstance(target, str)
            or source not in capability_ids
            or target not in capability_ids
        ):
            continue
        if source == target:
            _add_issue(
                issues,
                f"/relations/{index}/dependsOnCapabilityId",
                "DEPENDENCY_CYCLE",
                f"dependsOn self-edge is not allowed: {source}",
            )
            continue
        dependencies[source].append((target, index))

    states: dict[str, int] = {}
    stack: list[str] = []
    positions: dict[str, int] = {}

    def visit(capability_id: str) -> None:
        states[capability_id] = 1
        positions[capability_id] = len(stack)
        stack.append(capability_id)
        for target, relation_index in sorted(dependencies.get(capability_id, ())):
            if states.get(target, 0) == 0:
                visit(target)
            elif states.get(target) == 1:
                cycle = stack[positions[target] :] + [target]
                _add_issue(
                    issues,
                    f"/relations/{relation_index}/dependsOnCapabilityId",
                    "DEPENDENCY_CYCLE",
                    f"dependsOn cycle detected: {' -> '.join(cycle)}",
                )
        stack.pop()
        positions.pop(capability_id)
        states[capability_id] = 2

    for capability_id in sorted(capability_ids):
        if states.get(capability_id, 0) == 0:
            visit(capability_id)


def _items(document: Any, key: str) -> tuple[Any, ...]:
    if not isinstance(document, Mapping):
        return ()
    values = document.get(key)
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(values)


def _add_issue(
    issues: list[ValidationIssue],
    path: str,
    code: str,
    message: str,
) -> None:
    issues.append(ValidationIssue(path=path, code=code, message=message))
