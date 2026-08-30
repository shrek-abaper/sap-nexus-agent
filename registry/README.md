# SAP Nexus Capability Registry

`capabilities.yaml` is the semantic capability registry for SAP Nexus Agent. It remains runtime-compatible with the current `JCO_RFC` Gateway while the contract gate validates executor binding readiness, OWL identity, governance consistency, and eval linkage.

The current active capabilities are:

```text
MM.Inventory.GetAvailability
-> executorBinding.bindingId = sap.mm.inventory.md04-stock-req-list
-> current runtime executor = JCO_RFC / BAPI_MATERIAL_STOCK_REQ_LIST

MM.PurchaseOrder.GetList
-> executorBinding.bindingId = sap.mm.purchaseorder.list-odata
-> current runtime executor = ODATA / API_PURCHASEORDER_PROCESS_SRV

MM.Material.GetInfo
-> executorBinding.bindingId = sap.mm.material.get-detail
-> current runtime executor = JCO_RFC / BAPI_MATERIAL_GET_DETAIL

MM.PR.CreateDraft
-> executorBinding.bindingId = sap.mm.pr.create-draft
-> current runtime executor = JCO_RFC / BAPI_PR_CREATE
-> WRITE: requires a recorded human confirmation before execution

SD.SalesOrder.GetList
-> executorBinding.bindingId = sap.sd.salesorder.getlist
-> current runtime executor = JCO_RFC / BAPI_SALESORDER_GETLIST

FI.AR.GetOpenItems
-> executorBinding.bindingId = sap.fi.ar.get-open-items
-> current runtime executor = JCO_RFC / BAPI_AR_ACC_GETOPENITEMS

FI.AP.GetOpenItems
-> executorBinding.bindingId = sap.fi.ap.get-open-items
-> current runtime executor = JCO_RFC / BAPI_AP_ACC_GETOPENITEMS
```

## Contract Boundary

```text
Capability Registry = business semantics, governance, evidence, eval linkage
Executor Binding Catalog = allowlisted technical binding metadata
Gateway Family = protocol execution only
```

Agent, Workbench, LLM, and eval flows must use registered `capabilityId`. Callers must not provide or override `rfcName`, `bindingId`, REST URL, HTTP method, headers, credential references, tokens, or JSON payload mappings.

## Validation

Run:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
```

This command must not require SAP credentials, LLM credentials, network access, runtime traces, or Gateway startup.

Related regression:

```bash
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```
