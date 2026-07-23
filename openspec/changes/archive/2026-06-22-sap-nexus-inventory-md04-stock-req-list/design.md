## Design

### Runtime Path

```text
MM.Inventory.GetAvailability
-> Registry executor.type=JCO_RFC
-> Registry executor.rfcName=BAPI_MATERIAL_STOCK_REQ_LIST
-> Java Gateway validate / execute
-> JCo function import MATERIAL_LONG or MATERIAL, PLANT, optional MRP_AREA
-> MRP_IND_LINES stock row extraction
-> ExecutionResult.data.availableQuantity
-> Python ReasoningFact / Workbench narrative
```

### MD04 Stock Row Rule

The first validation rule uses the MD04 stock/requirements list table `MRP_IND_LINES`:

- Prefer a row with `MRP_ELEMENT_IND = WB`.
- Fallback to a row whose `MRP_ELEMNT` text equals `Stock`.
- Extract `AVAIL_QTY1` as `availableQuantity`.
- Preserve safe evidence fields such as `sourceTable=MRP_IND_LINES`, `sourceField=AVAIL_QTY1`, `mrpElementInd`, `mrpElement`, and `availableDate`.

This is intentionally a first stock-row rule, not a net availability calculation across future receipts and requirements.

### Registry Mapping

The registry remains capability-centric. The capability ID, domain, business object, governance, and Agent contracts stay stable. Only the technical executor mapping changes.

### Future Multi-Executor Contract

A later change should generalize `executor.type` dispatch:

```text
JCO_RFC -> RFC/BAPI through Java JCo
CDS     -> CDS view query through an SAP-supported read interface
ODATA   -> SAP Gateway / OData service call
```

The Agent and UI must continue to select only `capabilityId`; they must not submit RFC names, CDS view names, or OData URLs.
