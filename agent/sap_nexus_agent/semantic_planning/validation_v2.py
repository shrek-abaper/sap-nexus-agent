"""PlanGraph v2 validator (semantic-plan-authoring-v2).

Reuses S1 ``semantic_planning.validation`` internal primitives (same-package
import of ``_validate_*`` functions) and adds partition isolation + ref
checks. ``_validate_plan_shape`` is S1-specific (hardcoded v1 schema), so v2
provides ``_validate_plan_shape_v2`` loading ``plan-graph-v2.schema.json``.

Design Doc: docs/superpowers/specs/2026-08-03-sap-nexus-semantic-plan-authoring-v2-design.md §4.3
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

import jsonschema

from .contracts import (
    PlanValidationReport,
    RegistrySnapshot,
    ValidationIssue,
)
from .graph import ImmutableSemanticGraph
from .validation import (
    _canonical_issues,
    _is_read_only,
    _load_schema,
    _plan_schema_error_details,
    _plan_unique_items_is_semantic,
    _to_json_value,
    _unique_items_is_conversion_artifact,
    _validate_edges,
    _validate_goal_outputs,
    _validate_nodes_and_projections,
    _validate_parameter_source,
    _validate_plan_governance,
    _validate_plan_stable_ids,
    _validate_snapshot_and_goal_identity,
    _validate_topological_order,
)

_SOURCE_KIND_REGISTERED_DEFAULT = "registeredDefault"


def validate_plan_graph_v2(
    graph: ImmutableSemanticGraph,
    snapshot: RegistrySnapshot,
    goal_spec: dict[str, Any],
    plan_graph: dict[str, Any],
) -> PlanValidationReport:
    issues: list[ValidationIssue] = []
    normalized_plan = _validate_plan_shape_v2(plan_graph, issues)
    if issues:
        return PlanValidationReport(False, _canonical_issues(issues))

    _validate_snapshot_and_goal_identity(snapshot, goal_spec, normalized_plan, issues)
    node_index = _validate_nodes_and_projections(graph, normalized_plan, issues)
    _validate_parameter_sources_v2(graph, goal_spec, node_index, issues)
    _validate_edges(graph, node_index, normalized_plan, issues)
    _validate_topological_order(node_index, normalized_plan, issues)
    _validate_plan_governance(goal_spec, node_index, issues)
    _validate_goal_outputs(goal_spec, node_index, normalized_plan, issues)
    _validate_partitions(normalized_plan, node_index, issues)
    _validate_refs(normalized_plan, snapshot, issues)
    ordered = _canonical_issues(issues)
    return PlanValidationReport(valid=not ordered, issues=ordered)


def _validate_plan_shape_v2(
    plan_graph: Any,
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    candidates: list[tuple[str, ValidationIssue]] = []
    normalized = _to_json_value(plan_graph, (), "", "__plan__", "", candidates)
    conversion_issues = [issue for _, issue in candidates]
    conversion_paths = {issue.path for issue in conversion_issues}
    issues.extend(conversion_issues)

    validator = jsonschema.Draft202012Validator(
        _load_schema("plan-graph-v2.schema.json")
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
            path = "".join(f"/{token}" for token in tokens)
            if error.instance is None and path in conversion_paths:
                continue
            issues.append(ValidationIssue(path, "SCHEMA_INVALID", message))

    if isinstance(normalized, dict):
        _validate_plan_stable_ids(normalized, issues)
        return normalized
    return {}


def _validate_parameter_sources_v2(
    graph: ImmutableSemanticGraph,
    goal_spec: Mapping[str, Any],
    node_index: Mapping[str, tuple[int, Mapping[str, Any], Mapping[str, Any]]],
    issues: list[ValidationIssue],
) -> None:
    """v2 parameter source 校验：前 3 源复用 S1 ``_validate_parameter_source``，
    ``registeredDefault`` 走 v2 自定义分支（本期 compiler 不产出，出现即报
    ``RESERVED_SOURCE_NOT_AUTHORED``）。"""
    del graph
    constraints = {
        constraint["name"]: constraint
        for constraint in goal_spec.get("constraints", ())
        if isinstance(constraint, Mapping)
    }
    for node_id in sorted(node_index):
        node_position, node, capability = node_index[node_id]
        inputs = {item["name"]: item for item in capability["inputs"]}
        bindings: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
        for binding_index, binding in enumerate(node["parameterBindings"]):
            parameter_name = binding["parameterName"]
            input_field = inputs.get(parameter_name)
            if input_field is None:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_position}/parameterBindings/{binding_index}/parameterName",
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
                        f"/nodes/{node_position}/parameterBindings",
                        "PARAMETER_SOURCE_MISSING",
                        f"required parameter has no source: {parameter_name}",
                    )
                )
            for duplicate_index, _ in matches[1:]:
                issues.append(
                    ValidationIssue(
                        f"/nodes/{node_position}/parameterBindings/{duplicate_index}/parameterName",
                        "PARAMETER_SOURCE_DUPLICATE",
                        f"parameter has multiple sources: {parameter_name}",
                    )
                )
            if len(matches) == 1:
                binding_index, binding = matches[0]
                source = binding["source"]
                if source["kind"] == _SOURCE_KIND_REGISTERED_DEFAULT:
                    _validate_registered_default_source(
                        node_position, binding_index, input_field, source, issues
                    )
                else:
                    _validate_parameter_source(
                        node_position,
                        binding_index,
                        input_field,
                        source,
                        constraints,
                        node_index,
                        issues,
                    )


def _validate_registered_default_source(
    node_position: int,
    binding_index: int,
    input_field: Mapping[str, Any],
    source: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    """registeredDefault 源本期 reserved：compiler 不产出。

    若出现，校验 semanticType 须匹配 input；不论匹配与否，报
    ``RESERVED_SOURCE_NOT_AUTHORED``（fail-closed，提示该源本期未激活）。
    """
    base_path = (
        f"/nodes/{node_position}/parameterBindings/{binding_index}/source"
    )
    if source.get("semanticType") != input_field["semanticType"]:
        issues.append(
            ValidationIssue(
                f"{base_path}/semanticType",
                "PARAMETER_SOURCE_MISSING",
                "registeredDefault semanticType does not match parameter",
            )
        )
    issues.append(
        ValidationIssue(
            base_path,
            "RESERVED_SOURCE_NOT_AUTHORED",
            "registeredDefault source is reserved and not authored this phase",
        )
    )


def _validate_partitions(
    plan_graph: Mapping[str, Any],
    node_index: Mapping[str, tuple[int, Mapping[str, Any], Mapping[str, Any]]],
    issues: list[ValidationIssue],
) -> None:
    read = list(plan_graph.get("readPartition", ()))
    action = list(plan_graph.get("actionPartition", ()))
    node_ids = set(node_index)
    if set(read) | set(action) != node_ids:
        issues.append(
            ValidationIssue(
                "/readPartition",
                "PARTITION_COVERAGE",
                "readPartition ∪ actionPartition must equal all node ids",
            )
        )
    if set(read) & set(action):
        issues.append(
            ValidationIssue(
                "/actionPartition",
                "PARTITION_OVERLAP",
                "readPartition ∩ actionPartition must be empty",
            )
        )
    # readPartition 中节点须为 read-only（节点 governance 维度）
    for node_id in read:
        entry = node_index.get(node_id)
        if entry is None:
            continue
        _node_position, node, _capability = entry
        governance = node.get("governance", {})
        # Adapt node governance to capability shape expected by _is_read_only
        node_capability_view = {
            "kind": governance.get("capabilityKind"),
            "governance": governance,
        }
        if not _is_read_only(node_capability_view):
            issues.append(
                ValidationIssue(
                    "/readPartition",
                    "PARTITION_GOVERNANCE_VIOLATION",
                    f"non-read-only node in readPartition: {node_id}",
                )
            )


def _validate_refs(
    plan_graph: Mapping[str, Any],
    snapshot: RegistrySnapshot,
    issues: list[ValidationIssue],
) -> None:
    # 本期 projectionRef/ruleSetRefs 空 -> 通过；非空校验在 Task 5
    return None
