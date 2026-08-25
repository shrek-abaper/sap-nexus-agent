import importlib
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_schema(name: str) -> dict:
    with open(REPO_ROOT / "schemas" / name, encoding="utf-8") as f:
        return json.load(f)


def _load_yaml(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))


def _clone(value: dict) -> dict:
    return json.loads(json.dumps(value))


def _validate_plan_graph_definition(definition: str, instance: dict) -> None:
    schema = _load_schema("plan-graph.schema.json")
    jsonschema.validate(
        instance,
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/$defs/{definition}",
            "$defs": schema["$defs"],
        },
    )


def _goal_spec() -> dict:
    return {
        "goalSpecVersion": 1,
        "goalId": "goal-001",
        "goalType": "inventoryAvailability",
        "executionMode": "READ_ONLY",
        "desiredFactTypes": ["sapnexus:InventoryAvailabilityFact"],
        "constraints": [
            {
                "name": "material",
                "semanticType": "sapnexus:MaterialNumber",
                "value": "MAT-001",
            },
            {
                "name": "plant",
                "semanticType": "sapnexus:Plant",
                "value": "1000",
            },
        ],
    }


def _plan_graph() -> dict:
    return {
        "planGraphVersion": 1,
        "planId": "plan-001",
        "goalId": "goal-001",
        "executionMode": "READ_ONLY",
        "snapshotId": "sha256:" + "a" * 64,
        "nodes": [
            {
                "nodeId": "inventory",
                "capabilityId": "MM.Inventory.GetAvailability",
                "parameterBindings": [
                    {
                        "parameterName": "material",
                        "source": {"kind": "goalConstraint", "constraintName": "material"},
                    },
                    {
                        "parameterName": "plant",
                        "source": {"kind": "goalConstraint", "constraintName": "plant"},
                    },
                ],
                "producesFactTypes": ["sapnexus:InventoryAvailabilityFact"],
                "governance": {
                    "capabilityKind": "Function",
                    "sideEffect": "none",
                    "requiresApproval": False,
                    "approvalPolicy": "not_required",
                },
            },
            {
                "nodeId": "purchaseOrders",
                "capabilityId": "MM.PurchaseOrder.GetList",
                "parameterBindings": [
                    {
                        "parameterName": "material",
                        "source": {"kind": "goalConstraint", "constraintName": "material"},
                    },
                    {
                        "parameterName": "plant",
                        "source": {"kind": "goalConstraint", "constraintName": "plant"},
                    },
                ],
                "producesFactTypes": ["sapnexus:PurchaseOrderSupplyFact"],
                "governance": {
                    "capabilityKind": "Function",
                    "sideEffect": "none",
                    "requiresApproval": False,
                    "approvalPolicy": "not_required",
                },
            },
        ],
        "edges": [],
        "topologicalOrder": ["inventory", "purchaseOrders"],
        "goalOutputs": [
            {
                "factTypeId": "sapnexus:InventoryAvailabilityFact",
                "producerNodeId": "inventory",
            },
            {
                "factTypeId": "sapnexus:PurchaseOrderSupplyFact",
                "producerNodeId": "purchaseOrders",
            },
        ],
    }


def _registry_snapshot() -> dict:
    source_versions = {
        "ontology/capability-relations.yaml": 2,
        "ontology/fact-types.yaml": 3,
        "registry/capabilities.yaml": 2,
        "registry/executor-bindings.yaml": 1,
        "registry/semantic-types.yaml": 3,
    }
    return {
        "snapshotVersion": 1,
        "canonicalizationVersion": 1,
        "snapshotId": "sha256:" + "b" * 64,
        "sources": [
            {
                "path": path,
                "documentVersion": version,
                "digest": "sha256:" + str(index) * 64,
            }
            for index, (path, version) in enumerate(source_versions.items(), start=1)
        ],
    }


def test_package_is_importable():
    module = importlib.import_module("sap_nexus_agent")
    assert module.__version__ == "0.1.0"


def test_contract_files_are_valid_json():
    for path in [Path("schemas/call-plan.schema.json"), Path("schemas/reasoning-fact.schema.json")]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["type"] == "object"
        assert payload["required"]
        assert payload["properties"]


def test_approval_record_schema_accepts_valid_record():
    schema = _load_schema("approval-record.schema.json")
    record = {
        "approvalId": "appr-001",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:abc123",
        "parameters": {"material": "M001", "plant": "1000"},
        "approver": "user@example.com",
        "approvedAt": "2026-07-16T10:00:00Z",
        "expiresAt": "2026-07-16T10:10:00Z",
        "status": "approved",
    }
    jsonschema.validate(record, schema)


def test_approval_record_schema_rejects_missing_hash():
    schema = _load_schema("approval-record.schema.json")
    record = {
        "approvalId": "appr-001",
        "capabilityId": "MM.PR.CreateDraft",
        "parameters": {"material": "M001"},
        "approver": "user@example.com",
        "approvedAt": "2026-07-16T10:00:00Z",
        "expiresAt": "2026-07-16T10:10:00Z",
        "status": "approved",
    }
    try:
        jsonschema.validate(record, schema)
        assert False, "should reject missing parameterSnapshotHash"
    except jsonschema.ValidationError:
        pass


def test_approval_record_schema_accepts_complete_plan_aware_binding():
    schema = _load_schema("approval-record.schema.json")
    record = {
        "approvalId": "appr-plan-21",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:parameters",
        "parameters": {"material": "M001"},
        "approver": "run-owner",
        "approvedAt": "2026-08-05T08:00:00Z",
        "expiresAt": "2026-08-05T08:10:00Z",
        "status": "approved",
        "registrySnapshotId": "snapshot-21",
        "capabilityVersion": "2.1.0",
        "approvalSubjectHash": "sha256:subject-21",
    }

    jsonschema.validate(record, schema)


def test_approval_record_schema_rejects_partial_plan_aware_binding():
    schema = _load_schema("approval-record.schema.json")
    record = {
        "approvalId": "appr-plan-21",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:parameters",
        "parameters": {"material": "M001"},
        "approver": "run-owner",
        "approvedAt": "2026-08-05T08:00:00Z",
        "expiresAt": "2026-08-05T08:10:00Z",
        "status": "approved",
        "registrySnapshotId": "snapshot-21",
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, schema)


def test_action_result_schema_accepts_success():
    schema = _load_schema("action-result.schema.json")
    result = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    jsonschema.validate(result, schema)


def test_action_result_schema_accepts_approval_reject():
    schema = _load_schema("action-result.schema.json")
    result = {
        "traceId": "trace-002",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "none",
        "returnMessages": [],
        "durationMs": 5,
        "errorType": "APPROVAL_REQUIRED",
    }
    jsonschema.validate(result, schema)


def test_capability_schema_action_requires_sap_write():
    schema = _load_schema("capability.schema.json")
    action_cap = {
        "version": 2,
        "capabilities": [
            {
                "capabilityId": "MM.PR.CreateDraft",
                "name": "PR Create",
                "description": "create PR",
                "status": "active",
                "kind": "Action",
                "domain": "MM",
                "businessObject": "PurchaseRequisition",
                "ontologyIri": "sapnexus:MM_PR_CreateDraft",
                "semanticType": "sapnexus:PurchaseRequisitionCreateAction",
                "inputs": [{"name": "material", "semanticType": "sapnexus:MaterialNumber", "bindingKind": "identifier", "required": True, "type": "string", "sapParameter": "MATERIAL"}],
                "outputs": [{"name": "prNumber", "semanticType": "sapnexus:PrNumber", "type": "string", "evidenceRole": "primaryFact", "factTypeRef": "sapnexus:PurchaseRequisitionCreatedFact"}],
                "executor": {"type": "JCO_RFC", "rfcName": "BAPI_PR_CREATE", "inputMapping": {"material": "PRITEM.MATERIAL"}, "outputMapping": {"prNumber": "EXPORTS.NUMBER"}},
                "executorBinding": {"type": "JCO_RFC", "bindingId": "sap.mm.pr.create-draft"},
                "evalLinkage": {"evalFile": "evals/pr_create_cases.json", "caseIds": ["pr-create-success-direct"]},
                "governance": {"sideEffect": "sap_write", "requiresApproval": True, "approvalPolicy": "human_required", "dataClassification": "internal", "auditRequired": True},
            }
        ],
    }
    jsonschema.validate(action_cap, schema)


def test_capability_schema_action_with_wrong_side_effect_rejected():
    schema = _load_schema("capability.schema.json")
    action_cap = {
        "version": 2,
        "capabilities": [
            {
                "capabilityId": "MM.PR.CreateDraft",
                "name": "PR Create",
                "description": "create PR",
                "status": "active",
                "kind": "Action",
                "domain": "MM",
                "businessObject": "PurchaseRequisition",
                "ontologyIri": "sapnexus:MM_PR_CreateDraft",
                "semanticType": "sapnexus:PurchaseRequisitionCreateAction",
                "inputs": [{"name": "material", "semanticType": "sapnexus:MaterialNumber", "bindingKind": "identifier", "required": True, "type": "string", "sapParameter": "MATERIAL"}],
                "outputs": [{"name": "prNumber", "semanticType": "sapnexus:PrNumber", "type": "string", "evidenceRole": "primaryFact", "factTypeRef": "sapnexus:PurchaseRequisitionCreatedFact"}],
                "executor": {"type": "JCO_RFC", "rfcName": "BAPI_PR_CREATE", "inputMapping": {"material": "PRITEM.MATERIAL"}, "outputMapping": {"prNumber": "EXPORTS.NUMBER"}},
                "executorBinding": {"type": "JCO_RFC", "bindingId": "sap.mm.pr.create-draft"},
                "evalLinkage": {"evalFile": "evals/pr_create_cases.json", "caseIds": ["pr-create-success-direct"]},
                "governance": {"sideEffect": "none", "requiresApproval": True, "approvalPolicy": "human_required", "dataClassification": "internal", "auditRequired": True},
            }
        ],
    }
    try:
        jsonschema.validate(action_cap, schema)
        assert False, "Action with sideEffect=none should be rejected"
    except jsonschema.ValidationError:
        pass


def test_capability_registry_v2_declares_fact_binding_contract():
    registry = _load_yaml("registry/capabilities.yaml")
    jsonschema.validate(registry, _load_schema("capability.schema.json"))

    assert registry["version"] == 2
    by_id = {item["capabilityId"]: item for item in registry["capabilities"]}
    expected = {
        "MM.Inventory.GetAvailability": "sapnexus:InventoryAvailabilityFact",
        "MM.PurchaseOrder.GetList": "sapnexus:PurchaseOrderSupplyFact",
        "MM.PR.CreateDraft": "sapnexus:PurchaseRequisitionCreatedFact",
    }
    for capability_id, fact_type_id in expected.items():
        capability = by_id[capability_id]
        assert all(item["bindingKind"] == "identifier" for item in capability["inputs"])
        primary = [item for item in capability["outputs"] if item["evidenceRole"] == "primaryFact"]
        assert sorted({item["factTypeRef"] for item in primary}) == [fact_type_id]


def test_capability_schema_accepts_current_registry_input_patterns():
    registry = _load_yaml("registry/capabilities.yaml")

    jsonschema.validate(registry, _load_schema("capability.schema.json"))

    patterns = [
        input_["pattern"]
        for capability in registry["capabilities"]
        for input_ in capability["inputs"]
        if "pattern" in input_
    ]
    # Input patterns in registry order: GetAvailability.plant, GetList.vendor
    # (added with the sanitized/real vendor-code shape fix), GetList.plant,
    # Material.GetInfo.plant (T3 task 5.2, same plantCode shape),
    # PR.CreateDraft.plant (B1.5, aligned with plantCode).
    assert patterns == [
        "^[A-Z0-9]{4}$",
        "^[A-Z0-9]{1,10}$",
        "^[A-Z0-9]{4}$",
        "^[A-Z0-9]{4}$",
        "^[A-Z0-9]{4}$",
    ]


@pytest.mark.parametrize(
    ("pattern", "expected_validator"),
    [("", "minLength"), (7, "type")],
)
def test_capability_schema_rejects_invalid_input_pattern(pattern, expected_validator):
    registry = _load_yaml("registry/capabilities.yaml")
    registry["capabilities"][0]["inputs"][1]["pattern"] = pattern
    validator = jsonschema.Draft202012Validator(
        _load_schema("capability.schema.json")
    )

    errors = list(validator.iter_errors(registry))

    pattern_errors = [
        error
        for error in errors
        if tuple(error.absolute_path) == ("capabilities", 0, "inputs", 1, "pattern")
    ]
    assert [error.validator for error in pattern_errors] == [expected_validator]


def test_initial_fact_type_and_relation_catalogs_validate():
    fact_types = _load_yaml("ontology/fact-types.yaml")
    relations = _load_yaml("ontology/capability-relations.yaml")
    jsonschema.validate(fact_types, _load_schema("fact-type-catalog.schema.json"))
    jsonschema.validate(relations, _load_schema("capability-relation.schema.json"))

    assert {item["factTypeId"] for item in fact_types["factTypes"]} == {
        "sapnexus:InventoryAvailabilityFact",
        "sapnexus:PurchaseOrderSupplyFact",
        "sapnexus:MaterialInfoFact",
        "sapnexus:PurchaseRequisitionCreatedFact",
    }
    assert relations == {"version": 2, "relations": []}


def test_executor_binding_catalog_with_sap_write_validates():
    bindings = _load_yaml("registry/executor-bindings.yaml")

    jsonschema.validate(bindings, _load_schema("executor-binding.schema.json"))

    assert any(
        binding["constraints"]["sideEffect"] == "sap_write"
        for binding in bindings["bindings"]
    )


def test_executor_binding_schema_rejects_unknown_side_effect():
    bindings = _load_yaml("registry/executor-bindings.yaml")
    bindings["bindings"][0]["constraints"]["sideEffect"] = "destructive"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bindings, _load_schema("executor-binding.schema.json"))


def test_capability_v2_rejects_invalid_binding_variants():
    registry = _load_yaml("registry/capabilities.yaml")
    schema = _load_schema("capability.schema.json")

    # An identifier input MAY declare satisfiableByFactType: bindingKind says
    # what the parameter is, satisfiableByFactType says where it may also come
    # from. Requirement: registry-ontology-contract, scenario "Identifier input
    # declares Fact Type reference". Positive coverage lives in
    # agent/tests/test_identifier_fact_binding.py.
    identifier_with_fact = json.loads(json.dumps(registry))
    identifier_with_fact["capabilities"][0]["inputs"][0]["satisfiableByFactType"] = (
        "sapnexus:InventoryAvailabilityFact"
    )
    jsonschema.validate(identifier_with_fact, schema)

    fact_without_reference = json.loads(json.dumps(registry))
    fact_without_reference["capabilities"][0]["inputs"][0]["bindingKind"] = "fact"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(fact_without_reference, schema)

    primary_without_fact = json.loads(json.dumps(registry))
    del primary_without_fact["capabilities"][0]["outputs"][0]["factTypeRef"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(primary_without_fact, schema)


def test_binding_source_kind_enum_is_exactly_three_kinds():
    """The `binding.sources[].kind` enum is pinned: no `sessionContext` kind
    exists or is introduced by derived-parameter-binding (design Decision 15).

    `capabilityOutput` stays deliberately unwired at the extraction layer — it
    is defect D2's fixed landing point, pinned by the two xfail placeholders in
    agent/tests/test_binding_sources.py. Upstream derivation in this change is
    authored as a plan-graph `factField` source instead, which is a different
    vocabulary in a different schema.
    """
    expected = ["userUtterance", "capabilityOutput", "default"]

    def _source_kind_enums(node):
        """Every `kind` enum that declares a binding source, at any depth.

        `extraction-declaration.schema.json` declares its enum inline rather
        than under `$defs`, so the walk is recursive; the `userUtterance`
        membership test is what distinguishes a source-kind enum from the
        unrelated `capability.kind` and `extractionMatcher.kind` enums.
        """
        if isinstance(node, dict):
            enum = (node.get("properties") or {}).get("kind", {})
            if isinstance(enum, dict) and "userUtterance" in (enum.get("enum") or []):
                yield enum["enum"]
            for value in node.values():
                yield from _source_kind_enums(value)
        elif isinstance(node, list):
            for item in node:
                yield from _source_kind_enums(item)

    for schema_name in ("capability.schema.json", "extraction-declaration.schema.json"):
        raw = (REPO_ROOT / "schemas" / schema_name).read_text(encoding="utf-8")
        assert "sessionContext" not in raw, schema_name
        enums = list(_source_kind_enums(_load_schema(schema_name)))
        assert enums, f"{schema_name}: no source-kind enum found"
        for enum in enums:
            assert enum == expected, schema_name


def test_goal_spec_accepts_compact_instance():
    jsonschema.validate(_goal_spec(), _load_schema("goal-spec.schema.json"))


def test_plan_graph_matches_published_registry_and_relation_catalog():
    plan = _plan_graph()
    jsonschema.validate(plan, _load_schema("plan-graph.schema.json"))

    registry = _load_yaml("registry/capabilities.yaml")
    relations = _load_yaml("ontology/capability-relations.yaml")
    capabilities = {item["capabilityId"]: item for item in registry["capabilities"]}
    constraints = {item["name"] for item in _goal_spec()["constraints"]}

    assert plan["edges"] == relations["relations"] == []
    for node in plan["nodes"]:
        capability = capabilities[node["capabilityId"]]
        inputs = {item["name"]: item for item in capability["inputs"]}
        for binding in node["parameterBindings"]:
            source = binding["source"]
            assert source["kind"] == "goalConstraint"
            assert source["constraintName"] in constraints
            assert inputs[binding["parameterName"]]["bindingKind"] == "identifier"
        assert node["producesFactTypes"] == sorted(
            {output["factTypeRef"] for output in capability["outputs"] if output["evidenceRole"] == "primaryFact"}
        )


@pytest.mark.parametrize(
    "source",
    [
        {"kind": "goalConstraint", "constraintName": "material"},
        {"kind": "literal", "semanticType": "sapnexus:Plant", "value": "1000"},
        {
            "kind": "factField",
            "producerNodeId": "producer",
            "factTypeId": "sapnexus:ExampleFact",
            "field": "exampleField",
        },
    ],
)
def test_plan_graph_parameter_source_union_accepts_standalone_shapes(source):
    _validate_plan_graph_definition("parameterSource", source)


@pytest.mark.parametrize(
    "edge",
    [
        {
            "edgeId": "data-edge",
            "kind": "data",
            "fromNodeId": "producer",
            "toNodeId": "consumer",
            "factTypeId": "sapnexus:ExampleFact",
        },
        {
            "edgeId": "dependency-edge",
            "kind": "dependency",
            "fromNodeId": "prerequisite",
            "toNodeId": "dependent",
        },
    ],
)
def test_plan_graph_edge_union_accepts_standalone_shapes(edge):
    _validate_plan_graph_definition("edge", edge)


def test_registry_snapshot_accepts_canonical_manifest():
    snapshot = _registry_snapshot()
    jsonschema.validate(snapshot, _load_schema("registry-snapshot.schema.json"))
    assert [source["documentVersion"] for source in snapshot["sources"]] == [
        _load_yaml(source["path"])["version"] for source in snapshot["sources"]
    ]


@pytest.mark.parametrize(
    ("schema_name", "instance_factory"),
    [
        ("goal-spec.schema.json", _goal_spec),
        ("plan-graph.schema.json", _plan_graph),
        ("registry-snapshot.schema.json", _registry_snapshot),
    ],
)
def test_semantic_planning_schemas_reject_additional_properties(schema_name, instance_factory):
    instance = instance_factory()
    instance["unexpected"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load_schema(schema_name))


@pytest.mark.parametrize(
    ("schema_name", "instance_factory", "version_field"),
    [
        ("goal-spec.schema.json", _goal_spec, "goalSpecVersion"),
        ("plan-graph.schema.json", _plan_graph, "planGraphVersion"),
        ("registry-snapshot.schema.json", _registry_snapshot, "snapshotVersion"),
    ],
)
def test_semantic_planning_schemas_reject_version_drift(
    schema_name, instance_factory, version_field
):
    instance = instance_factory()
    instance[version_field] = 2

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load_schema(schema_name))


@pytest.mark.parametrize(
    "required_field",
    ["capabilityKind", "sideEffect", "requiresApproval", "approvalPolicy"],
)
def test_plan_graph_rejects_missing_governance_projection(required_field):
    plan = _plan_graph()
    del plan["nodes"][0]["governance"][required_field]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(plan, _load_schema("plan-graph.schema.json"))


@pytest.mark.parametrize("digest_target", ["snapshotId", "sourceDigest"])
def test_registry_snapshot_rejects_malformed_sha256(digest_target):
    snapshot = _registry_snapshot()
    if digest_target == "snapshotId":
        snapshot["snapshotId"] = "sha256:ABC123"
    else:
        snapshot["sources"][0]["digest"] = "sha256:too-short"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(snapshot, _load_schema("registry-snapshot.schema.json"))


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "permuted"])
def test_registry_snapshot_rejects_noncanonical_source_manifests(mutation):
    snapshot = _registry_snapshot()
    if mutation == "missing":
        snapshot["sources"].pop()
    elif mutation == "duplicate":
        snapshot["sources"][-1] = _clone(snapshot["sources"][-2])
    elif mutation == "unknown":
        snapshot["sources"][-1]["path"] = "registry/unknown.yaml"
    else:
        snapshot["sources"][0], snapshot["sources"][1] = (
            snapshot["sources"][1],
            snapshot["sources"][0],
        )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(snapshot, _load_schema("registry-snapshot.schema.json"))
