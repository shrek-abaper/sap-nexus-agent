import json
from pathlib import Path

import jsonschema
import yaml

from scripts.validate_registry_contract import load_registry_contract, validate_registry_contract


def test_inventory_capability_has_stable_binding_identity():
    contract = load_registry_contract(Path("registry/capabilities.yaml"))
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert errors == []
    inventory = contract.capability("MM.Inventory.GetAvailability")
    assert inventory.executor_binding_id == "sap.mm.inventory.md04-stock-req-list"
    assert inventory.executor_type == "JCO_RFC"


def test_function_with_write_side_effect_fails(tmp_path):
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(
        Path("registry/capabilities.yaml").read_text(encoding="utf-8").replace(
            "sideEffect: none", "sideEffect: write", 1
        ),
        encoding="utf-8",
    )

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))

    assert any("Function capability must have sideEffect=none" in error for error in errors)


def test_action_without_human_approval_fails(tmp_path):
    text = Path("registry/capabilities.yaml").read_text(encoding="utf-8")
    text = text.replace("kind: Function", "kind: Action", 1)
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(text, encoding="utf-8")

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))

    assert any("Action capability must require human approval" in error for error in errors)


def test_missing_eval_linkage_fails(tmp_path):
    text = Path("registry/capabilities.yaml").read_text(encoding="utf-8")
    start = text.index("    evalLinkage:")
    end = text.index("    governance:", start)
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(text[:start] + text[end:], encoding="utf-8")

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))

    assert any("evalLinkage" in error for error in errors)


def test_missing_semantic_inputs_fail(tmp_path):
    text = Path("registry/capabilities.yaml").read_text(encoding="utf-8")
    start = text.index("    inputs:")
    end = text.index("    outputs:", start)
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(text[:start] + text[end:], encoding="utf-8")

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))

    assert any("inputs are required" in error for error in errors)


def test_missing_output_evidence_role_fails(tmp_path):
    text = Path("registry/capabilities.yaml").read_text(encoding="utf-8")
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(text.replace("        evidenceRole: primaryFact\n", "", 1), encoding="utf-8")

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))

    assert any("outputs[availableQuantity].evidenceRole is required" in error for error in errors)


def test_unsafe_rest_json_binding_fails(tmp_path):
    repo_root = tmp_path
    (repo_root / "registry").mkdir()
    (repo_root / "evals").mkdir()
    (repo_root / "ontology").mkdir()
    (repo_root / "ontology" / "crm-credit.owl").write_text(
        """<?xml version="1.0"?>
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:NamedIndividual rdf:about="sapnexus:CRM_Customer_GetCreditStatus"/>
  <owl:Class rdf:about="sapnexus:CustomerCreditStatusFact"/>
</rdf:RDF>
""",
        encoding="utf-8",
    )
    (repo_root / "ontology" / "fact-types.yaml").write_text(
        """version: 3
factTypes:
  - factTypeId: sapnexus:CustomerCreditStatusFact
    name: Customer Credit Status Fact
    description: Credit status for an identified customer.
    businessObject: CustomerCredit
    predicate: sapnexus:hasCustomerCreditStatus
    semanticType: sapnexus:CustomerCreditStatus
    keyedBy:
      - sapnexus:CustomerId
    fields:
      - name: creditStatus
        semanticType: sapnexus:CreditStatus
        cardinality: one
        optional: false
        description: Credit status value published by the producer capability.
""",
        encoding="utf-8",
    )
    (repo_root / "registry" / "executor-bindings.yaml").write_text(
        """version: 1
bindings:
  - bindingId: external.crm.customer-credit.lookup
    type: REST_JSON
    systemRef: CRM_LEGACY
    method: POST
    url: https://example.invalid/secret
    pathTemplate: /api/customers/{customerId}/credit-status
    request:
      body: $.inputs
    response:
      dataMapping:
        creditStatus: $.body.status
    auth:
      credentialRef: CRM_LEGACY_TOKEN
      token: secret-token
    constraints:
      sideEffect: write
""",
        encoding="utf-8",
    )
    (repo_root / "evals" / "inventory_availability_cases.yaml").write_text(
        '{"cases":[{"id":"happy-path"}]}',
        encoding="utf-8",
    )
    registry = repo_root / "registry" / "capabilities.yaml"
    registry.write_text(
        """version: 2
capabilities:
  - capabilityId: CRM.Customer.GetCreditStatus
    name: Customer Credit Status
    description: Read customer credit status.
    status: active
    kind: Function
    domain: CRM
    businessObject: CustomerCredit
    ontologyIri: sapnexus:CRM_Customer_GetCreditStatus
    semanticType: sapnexus:CustomerCreditReadFunction
    inputs:
      - name: customerId
        semanticType: sapnexus:CustomerId
        bindingKind: identifier
        required: true
        type: string
        sapParameter: CUSTOMER_ID
    outputs:
      - name: creditStatus
        semanticType: sapnexus:CreditStatus
        type: string
        evidenceRole: primaryFact
        factTypeRef: sapnexus:CustomerCreditStatusFact
    executorBinding:
      type: REST_JSON
      bindingId: external.crm.customer-credit.lookup
    evalLinkage:
      evalFile: evals/inventory_availability_cases.yaml
      caseIds:
        - happy-path
    governance:
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
      dataClassification: internal
      auditRequired: true
""",
        encoding="utf-8",
    )

    fact_catalog_path = repo_root / "ontology" / "fact-types.yaml"
    assert fact_catalog_path.exists(), "isolated Registry v2 fixture must publish its Fact Types"
    fact_catalog = yaml.safe_load(fact_catalog_path.read_text(encoding="utf-8"))
    fact_catalog_schema = json.loads(
        Path("schemas/fact-type-catalog.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(fact_catalog, fact_catalog_schema)
    registry_payload = yaml.safe_load(registry.read_text(encoding="utf-8"))
    referenced_fact_types = {
        output["factTypeRef"]
        for capability in registry_payload["capabilities"]
        for output in capability["outputs"]
        if "factTypeRef" in output
    }
    published_fact_types = {
        fact_type["factTypeId"] for fact_type in fact_catalog["factTypes"]
    }
    assert referenced_fact_types <= published_fact_types

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=repo_root)

    assert not any("ontologyIri not found in ontology skeleton" in error for error in errors)
    assert any("REST_JSON Function binding must be read-only" in error for error in errors)
    assert any("REST_JSON binding must not contain raw url" in error for error in errors)
    assert any("REST_JSON auth must not contain token" in error for error in errors)


def test_unreferenced_unsafe_binding_still_fails(tmp_path):
    repo_root = tmp_path
    (repo_root / "registry").mkdir()
    (repo_root / "evals").mkdir()
    (repo_root / "ontology").mkdir()
    (repo_root / "registry" / "executor-bindings.yaml").write_text(
        Path("registry/executor-bindings.yaml").read_text(encoding="utf-8")
        + """
  - bindingId: external.unused.unsafe
    type: REST_JSON
    systemRef: CRM_LEGACY
    method: GET
    pathTemplate: /safe
    request:
      queryParams:
        id: $.inputs.id
    response:
      dataMapping:
        status: $.body.status
    auth:
      credentialRef: CRM_LEGACY_TOKEN
      apiKey: hardcoded
    constraints:
      sideEffect: none
""",
        encoding="utf-8",
    )
    (repo_root / "evals" / "inventory_availability_cases.yaml").write_text(
        Path("evals/inventory_availability_cases.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo_root / "ontology" / "sapnexus-core.owl").write_text(
        Path("ontology/sapnexus-core.owl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo_root / "ontology" / "mm-inventory.owl").write_text(
        Path("ontology/mm-inventory.owl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registry = repo_root / "registry" / "capabilities.yaml"
    registry.write_text(Path("registry/capabilities.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=repo_root)

    assert any("REST_JSON auth must not contain apiKey" in error for error in errors)


def test_odata_binding_missing_allowlist_fails(tmp_path):
    repo_root = tmp_path
    (repo_root / "registry").mkdir()
    (repo_root / "evals").mkdir()
    (repo_root / "ontology").mkdir()
    (repo_root / "registry" / "executor-bindings.yaml").write_text(
        """version: 1
bindings:
  - bindingId: sap.mm.inventory.odata
    type: ODATA
    constraints:
      sideEffect: none
""",
        encoding="utf-8",
    )
    (repo_root / "evals" / "inventory_availability_cases.yaml").write_text(
        '{"cases":[{"id":"happy-path"}]}',
        encoding="utf-8",
    )
    (repo_root / "ontology" / "mm-inventory.owl").write_text(
        "sapnexus:MM_Inventory_GetAvailability",
        encoding="utf-8",
    )
    registry = repo_root / "registry" / "capabilities.yaml"
    registry.write_text(
        """version: 2
capabilities:
  - capabilityId: MM.Inventory.GetAvailability
    name: Inventory Availability
    description: Read material availability.
    status: active
    kind: Function
    domain: MM
    businessObject: InventoryStock
    ontologyIri: sapnexus:MM_Inventory_GetAvailability
    semanticType: sapnexus:InventoryAvailabilityReadFunction
    inputs:
      - name: material
        semanticType: sapnexus:MaterialNumber
        bindingKind: identifier
        required: true
        type: string
        sapParameter: MATERIAL
    outputs:
      - name: availableQuantity
        semanticType: sapnexus:AvailableQuantity
        type: number
        evidenceRole: primaryFact
        factTypeRef: sapnexus:InventoryAvailabilityFact
    executorBinding:
      type: ODATA
      bindingId: sap.mm.inventory.odata
    evalLinkage:
      evalFile: evals/inventory_availability_cases.yaml
      caseIds:
        - happy-path
    governance:
      sideEffect: none
      requiresApproval: false
      approvalPolicy: not_required
      dataClassification: internal
      auditRequired: true
""",
        encoding="utf-8",
    )

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=repo_root)

    assert any("ODATA binding requires serviceRef" in error for error in errors)
    assert any("ODATA binding requires entitySet" in error for error in errors)


def test_capability_schema_declares_contract_metadata():
    schema = json.loads(Path("schemas/capability.schema.json").read_text(encoding="utf-8"))
    capability_properties = schema["$defs"]["capability"]["properties"]
    capability_required = schema["$defs"]["capability"]["required"]

    assert "executorBinding" in capability_properties
    assert "evalLinkage" in capability_properties
    assert "executorBinding" in capability_required
    assert "evalLinkage" in capability_required


def test_executor_binding_schema_constrains_future_executor_shapes():
    schema = json.loads(Path("schemas/executor-binding.schema.json").read_text(encoding="utf-8"))
    conditionals = schema["$defs"]["binding"]["allOf"]

    def required_for(executor_type: str) -> set[str]:
        for conditional in conditionals:
            if conditional["if"]["properties"]["type"]["const"] == executor_type:
                return set(conditional["then"]["required"])
        raise AssertionError(f"missing conditional for {executor_type}")

    assert {"serviceRef", "entitySet", "method"}.issubset(required_for("ODATA"))
    assert {"cdsEntity", "operation"}.issubset(required_for("CDS_ADT"))
    assert {"serviceRef", "entitySet", "method"}.issubset(required_for("CDS_ODATA"))


def test_inventory_ontology_identity_exists():
    contract = load_registry_contract(Path("registry/capabilities.yaml"))
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert errors == []
    owl_text = Path("ontology/mm-inventory.owl").read_text(encoding="utf-8")
    assert "sapnexus:MM_Inventory_GetAvailability" in owl_text


def test_missing_ontology_identity_fails(tmp_path):
    repo_root = tmp_path
    (repo_root / "registry").mkdir()
    (repo_root / "evals").mkdir()
    (repo_root / "ontology").mkdir()
    (repo_root / "registry" / "executor-bindings.yaml").write_text(
        Path("registry/executor-bindings.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo_root / "evals" / "inventory_availability_cases.yaml").write_text(
        Path("evals/inventory_availability_cases.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registry = repo_root / "registry" / "capabilities.yaml"
    registry.write_text(
        Path("registry/capabilities.yaml")
        .read_text(encoding="utf-8")
        .replace("sapnexus:MM_Inventory_GetAvailability", "sapnexus:MissingIdentity", 1),
        encoding="utf-8",
    )
    (repo_root / "ontology" / "sapnexus-core.owl").write_text("<rdf:RDF></rdf:RDF>", encoding="utf-8")
    (repo_root / "ontology" / "mm-inventory.owl").write_text("<rdf:RDF></rdf:RDF>", encoding="utf-8")

    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=repo_root)

    assert any("ontologyIri not found in ontology skeleton" in error for error in errors)
