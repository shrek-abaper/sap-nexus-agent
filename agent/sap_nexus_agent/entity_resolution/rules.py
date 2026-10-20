"""Loader and cross-reference validator for ontology/entity-resolution.yaml.

Schema shape is enforced by schemas/entity-resolution.schema.json through the
SemanticRelease asset validation; this module enforces the cross-references
the prompt requires (spec: entity-resolution-contracts):

- objectTypeId / identifierSemanticType match ontology/object-types.yaml
- searchCapabilityId exists and is a READ capability (sideEffect none,
  approvalPolicy not_required)
- parameterBindings reference existing capability inputs whose semanticType
  equals the object identifier semanticType
- displayNameField / candidateDisplayFields / distinguishingFields stay
  consistent with the declared searchable fields
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = "ontology/entity-resolution.yaml"
OBJECT_TYPES_PATH = "ontology/object-types.yaml"
CAPABILITIES_PATH = "registry/capabilities.yaml"
SCHEMA_PATH = "schemas/entity-resolution.schema.json"


@dataclass(frozen=True)
class ParameterBinding:
    capability_id: str
    input_name: str


@dataclass(frozen=True)
class EntityResolutionRule:
    object_type_id: str
    identifier_semantic_type: str
    identifier_field: str
    display_name_field: str
    search_capability_id: str
    searchable_fields: tuple[tuple[str, str], ...]
    distinguishing_fields: tuple[str, ...]
    organizational_filters: tuple[tuple[str, str], ...]
    languages: tuple[str, ...]
    confirm_exact_code: bool
    confirm_exact_label_unique: bool
    candidate_display_fields: tuple[str, ...]
    parameter_bindings: tuple[ParameterBinding, ...]

    @property
    def searchable_field_names(self) -> tuple[str, ...]:
        return tuple(field for field, _kind in self.searchable_fields)


@dataclass(frozen=True)
class ResolutionIssue:
    path: str
    code: str
    message: str


def _load_yaml(repo_root: Path, logical_path: str) -> dict[str, Any]:
    with open(repo_root / logical_path, encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{logical_path} must be a mapping")
    return document


def load_resolution_rules(repo_root: Path | None = None) -> tuple[EntityResolutionRule, ...]:
    """Parse entity-resolution.yaml into typed rules (schema-validated)."""
    root = repo_root or REPO_ROOT
    document = _load_yaml(root, RULES_PATH)
    schema = json.loads((root / SCHEMA_PATH).read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)
    rules: list[EntityResolutionRule] = []
    for entry in document["objectTypes"]:
        policy = entry["confirmationPolicy"]
        rules.append(
            EntityResolutionRule(
                object_type_id=entry["objectTypeId"],
                identifier_semantic_type=entry["identifierSemanticType"],
                identifier_field=entry["identifierField"],
                display_name_field=entry["displayNameField"],
                search_capability_id=entry["searchCapabilityId"],
                searchable_fields=tuple(
                    (field["field"], field["kind"]) for field in entry["searchableFields"]
                ),
                distinguishing_fields=tuple(entry["distinguishingFields"]),
                organizational_filters=tuple(
                    (flt["field"], flt["semanticType"])
                    for flt in entry["organizationalFilters"]
                ),
                languages=tuple(entry["languages"]),
                confirm_exact_code=policy["exactCode"] == "confirm",
                confirm_exact_label_unique=policy["exactLabelUnique"] == "confirm",
                candidate_display_fields=tuple(entry["candidateDisplayFields"]),
                parameter_bindings=tuple(
                    ParameterBinding(b["capabilityId"], b["inputName"])
                    for b in entry["parameterBindings"]
                ),
            )
        )
    return tuple(rules)


def _capabilities_by_id(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {cap["capabilityId"]: cap for cap in document.get("capabilities", [])}


def validate_rules(
    rules: tuple[EntityResolutionRule, ...] | None = None,
    repo_root: Path | None = None,
) -> tuple[ResolutionIssue, ...]:
    """Cross-check resolution rules against object types and the registry."""
    root = repo_root or REPO_ROOT
    if rules is None:
        rules = load_resolution_rules(root)
    object_types = {
        entry["objectTypeId"]: entry
        for entry in _load_yaml(root, OBJECT_TYPES_PATH)["objectTypes"]
    }
    capabilities = _capabilities_by_id(_load_yaml(root, CAPABILITIES_PATH))

    issues: list[ResolutionIssue] = []

    def issue(rule: EntityResolutionRule, code: str, message: str) -> None:
        issues.append(ResolutionIssue(rule.object_type_id, code, message))

    seen_ids: set[str] = set()
    for rule in rules:
        if rule.object_type_id in seen_ids:
            issue(rule, "ER_DUPLICATE_OBJECT_TYPE", "objectTypeId declared twice")
        seen_ids.add(rule.object_type_id)

        object_type = object_types.get(rule.object_type_id)
        if object_type is None:
            issue(rule, "ER_UNKNOWN_OBJECT_TYPE", "objectTypeId missing from object-types.yaml")
        elif object_type.get("semanticType") != rule.identifier_semantic_type:
            issue(
                rule,
                "ER_IDENTIFIER_TYPE_MISMATCH",
                "identifierSemanticType does not match object-types.yaml semanticType",
            )

        search_capability = capabilities.get(rule.search_capability_id)
        if search_capability is None:
            issue(rule, "ER_UNKNOWN_SEARCH_CAPABILITY", "searchCapabilityId not registered")
        else:
            governance = search_capability.get("governance", {})
            if governance.get("sideEffect") != "none":
                issue(rule, "ER_SEARCH_NOT_READ_ONLY", "search capability must have sideEffect none")
            if governance.get("approvalPolicy") != "not_required":
                issue(rule, "ER_SEARCH_NEEDS_APPROVAL", "search capability must not require approval")

        for binding in rule.parameter_bindings:
            capability = capabilities.get(binding.capability_id)
            if capability is None:
                issue(rule, "ER_UNKNOWN_BINDING_CAPABILITY",
                      f"parameterBinding capability {binding.capability_id} not registered")
                continue
            inputs = {inp["name"]: inp for inp in capability.get("inputs", [])}
            target = inputs.get(binding.input_name)
            if target is None:
                issue(rule, "ER_UNKNOWN_BINDING_INPUT",
                      f"{binding.capability_id} has no input {binding.input_name}")
            elif target.get("semanticType") != rule.identifier_semantic_type:
                issue(rule, "ER_BINDING_TYPE_MISMATCH",
                      f"{binding.capability_id}.{binding.input_name} semanticType "
                      f"{target.get('semanticType')} != {rule.identifier_semantic_type}")

        searchable = set(rule.searchable_field_names)
        distinguishing = set(rule.distinguishing_fields)
        displayable = searchable | distinguishing | {rule.identifier_field}
        if rule.display_name_field not in searchable:
            issue(rule, "ER_DISPLAY_NOT_SEARCHABLE",
                  "displayNameField must be declared as a searchable field")
        if rule.identifier_field not in rule.candidate_display_fields:
            issue(rule, "ER_IDENTIFIER_NOT_DISPLAYED",
                  "identifierField must appear in candidateDisplayFields")
        if rule.display_name_field not in rule.candidate_display_fields:
            issue(rule, "ER_DISPLAY_NAME_NOT_DISPLAYED",
                  "displayNameField must appear in candidateDisplayFields")
        for field in rule.distinguishing_fields:
            if field not in rule.candidate_display_fields:
                issue(rule, "ER_DISTINGUISHING_NOT_DISPLAYED",
                      f"distinguishingField {field} must appear in candidateDisplayFields")
        for field in rule.candidate_display_fields:
            if field not in displayable:
                issue(rule, "ER_DISPLAY_FIELD_UNBACKED",
                      f"candidateDisplayField {field} is not a declared searchable/distinguishing/identifier field")

    return tuple(issues)
