## Why

`MM.Inventory.GetAvailability` currently maps to `BAPI_MATERIAL_AVAILABILITY`, which depends on ATP availability behavior. In the target SAP environment, ATP is not enabled for the tested material/plant path, so the Workbench can return `0.0 EA` even though MD04 shows stock/requirements list data. The read-only inventory capability should use the MD04 stock/requirements BAPI for this MVP validation path.

## What Changes

- Keep the business capability ID `MM.Inventory.GetAvailability` stable.
- Change the registered JCo RFC executor from `BAPI_MATERIAL_AVAILABILITY` to `BAPI_MATERIAL_STOCK_REQ_LIST`.
- Normalize the MD04 current stock row from `MRP_IND_LINES` where `MRP_ELEMENT_IND=WB` / `MRP_ELEMNT=Stock` into `ExecutionResult.data.availableQuantity`.
- Preserve the existing Python Agent, Workbench, CallPlan, ReasoningFact, and narrative contract by continuing to expose `availableQuantity`, `material`, `plant`, and `unit` where available.
- Add tests for the MD04 stock-row extraction and registry mapping.

## Out Of Scope

- CDS and OData execution are not implemented in this change.
- RecommendationPlan, SAP Write Action, approvals, RBAC, multi-tenant runtime, and production deployment remain out of scope.

## Future Design Note

The follow-up Registry / Gateway contract should support executor dispatch by `executor.type`, including `JCO_RFC`, `CDS`, and `ODATA`, so capabilities can choose the best SAP access method without exposing technical endpoints to the Agent or UI.
