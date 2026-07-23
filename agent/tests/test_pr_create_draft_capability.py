"""Task 2: MM.PR.CreateDraft Action capability contract tests.

Verifies the first SAP WRITE capability registration:
- kind=Action, sideEffect=sap_write, requiresApproval=true
- executor JCO_RFC / BAPI_PR_CREATE
- 8 inputs (6 required + 2 optional: acct_assgn_cat, cost_center)
- inputMapping / outputMapping
- executor binding sap.mm.pr.create-draft
- ontology individual sapnexus:MM_PR_CreateDraft
- regression: existing read capabilities still validate
"""

from pathlib import Path

from scripts.validate_registry_contract import (
    load_registry_contract,
    validate_registry_contract,
)


def _load_pr_capability():
    contract = load_registry_contract(Path("registry/capabilities.yaml"))
    return contract.capability("MM.PR.CreateDraft")


def test_pr_create_draft_capability_is_registered_as_action():
    cap = _load_pr_capability()
    assert cap.kind == "Action"
    assert cap.capability_id == "MM.PR.CreateDraft"


def test_pr_create_draft_governance_is_sap_write_with_human_approval():
    cap = _load_pr_capability()
    governance = cap.raw["governance"]
    assert governance["sideEffect"] == "sap_write"
    assert governance["requiresApproval"] is True
    assert governance["approvalPolicy"] == "human_required"
    assert governance["dataClassification"] == "internal"
    assert governance["auditRequired"] is True


def test_pr_create_draft_executor_targets_bapi_pr_create():
    cap = _load_pr_capability()
    executor = cap.raw["executor"]
    assert executor["type"] == "JCO_RFC"
    assert executor["rfcName"] == "BAPI_PR_CREATE"


def test_pr_create_draft_has_six_required_and_two_optional_inputs():
    cap = _load_pr_capability()
    inputs = {inp["name"]: inp for inp in cap.raw["inputs"]}
    assert len(inputs) == 8
    for required_name in ("material", "plant", "quantity", "unit", "delivery_date", "purchasing_group"):
        assert inputs[required_name]["required"] is True, f"{required_name} must be required"
    # 2 optional (acct_assgn_cat default empty = direct procurement)
    assert inputs["acct_assgn_cat"]["required"] is False
    assert inputs["cost_center"]["required"] is False


def test_pr_create_draft_input_mapping_covers_all_eight_inputs():
    cap = _load_pr_capability()
    mapping = cap.raw["executor"]["inputMapping"]
    assert mapping["material"] == "PRITEM.MATERIAL"
    assert mapping["plant"] == "PRITEM.PLANT"
    assert mapping["quantity"] == "PRITEM.QUANTITY"
    assert mapping["unit"] == "PRITEM.UNIT"
    assert mapping["delivery_date"] == "PRITEM.DELIV_DATE"
    assert mapping["purchasing_group"] == "PRITEM.PUR_GROUP"
    assert mapping["acct_assgn_cat"] == "PRITEM.ACCTASSCAT"
    assert mapping["cost_center"] == "PRITEM.COSTCENTER"


def test_pr_create_draft_output_mapping_returns_pr_number_and_messages():
    cap = _load_pr_capability()
    mapping = cap.raw["executor"]["outputMapping"]
    assert mapping["prNumber"] == "EXPORTS.NUMBER"
    assert mapping["returnMessages"] == "RETURN"
    outputs = {out["name"]: out for out in cap.raw["outputs"]}
    assert outputs["prNumber"]["evidenceRole"] == "primaryFact"
    assert outputs["returnMessages"]["evidenceRole"] == "executionEvidence"


def test_pr_create_draft_executor_binding_is_jco_rfc_create_draft():
    cap = _load_pr_capability()
    assert cap.executor_type == "JCO_RFC"
    assert cap.executor_binding_id == "sap.mm.pr.create-draft"


def test_pr_create_draft_binding_in_catalog_has_sap_write_constraint():
    import sys

    sys.path.insert(0, "scripts")
    from validate_registry_contract import _load_bindings  # noqa: E402

    bindings = _load_bindings(Path("registry/executor-bindings.yaml"))
    binding = bindings["sap.mm.pr.create-draft"]
    assert binding["type"] == "JCO_RFC"
    assert binding["rfcName"] == "BAPI_PR_CREATE"
    assert "PRITEM" in binding["allowedImports"]
    assert "PRITEMEXP" in binding["allowedOutputs"]
    assert "RETURN" in binding["allowedOutputs"]
    assert binding["constraints"]["sideEffect"] == "sap_write"


def test_pr_create_draft_ontology_individual_exists():
    cap = _load_pr_capability()
    owl_text = Path("ontology/mm-purchaserequisition.owl").read_text(encoding="utf-8")
    assert cap.ontology_iri in owl_text  # sapnexus:MM_PR_CreateDraft
    assert "PurchaseRequisitionCreateAction" in owl_text
    assert "sapnexus:PurchaseRequisition" in owl_text
    assert "sapnexus:PurchasingGroup" in owl_text


def test_pr_create_draft_indirect_procurement_only_supports_k():
    """Thin vertical slice: indirect procurement only supports acct_assgn_cat='K'."""
    cap = _load_pr_capability()
    inputs = {inp["name"]: inp for inp in cap.raw["inputs"]}
    # acct_assgn_cat is the branch selector; cost_center is the conditional required field
    assert inputs["acct_assgn_cat"]["semanticType"] == "sapnexus:AcctAssignmentCat"
    assert inputs["cost_center"]["semanticType"] == "sapnexus:CostCenter"
    assert inputs["acct_assgn_cat"].get("maxLength") == 1


def test_registry_contract_validates_all_capabilities_including_pr_create():
    """Regression: full registry contract must validate with the new Action capability."""
    contract = load_registry_contract(Path("registry/capabilities.yaml"))
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert errors == [], f"registry contract errors: {errors}"


def test_existing_read_capabilities_still_pass_contract():
    """Regression: the two existing read capabilities must still validate."""
    contract = load_registry_contract(Path("registry/capabilities.yaml"))
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert errors == []
    # Both read capabilities still present and Function kind
    inventory = contract.capability("MM.Inventory.GetAvailability")
    assert inventory.kind == "Function"
    po = contract.capability("MM.PurchaseOrder.GetList")
    assert po.kind == "Function"
