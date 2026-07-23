## 1. OpenSpec

- [x] 1.1 Create `sap-nexus-inventory-md04-stock-req-list` change.
- [x] 1.2 Document the ATP BAPI mismatch and MD04 stock-row extraction rule.
- [x] 1.3 Add delta specs for Gateway execution and Agent evidence expectations.

## 2. Gateway And Registry

- [x] 2.1 Add failing Gateway test for extracting `availableQuantity` from `MRP_IND_LINES` stock row.
- [x] 2.2 Change registry executor mapping to `BAPI_MATERIAL_STOCK_REQ_LIST`.
- [x] 2.3 Update JCo executor output extraction for MD04 stock row while preserving existing BAPI availability compatibility where possible.
- [x] 2.4 Update Gateway registry/execution tests for the new RFC name.

## 3. Agent And Docs

- [x] 3.1 Confirm Python Agent and Workbench still consume normalized `availableQuantity` without contract changes.
- [x] 3.2 Update runbooks/wiki references from ATP BAPI to MD04 stock requirements BAPI where relevant.
- [x] 3.3 Note future `JCO_RFC` / `CDS` / `ODATA` executor type direction without implementing it.

## 4. Verification

- [x] 4.1 Run focused Gateway tests.
- [x] 4.2 Run `scripts/verify-agent-callplan-evidence.sh`.
- [x] 4.3 Run `npm --prefix frontend run verify`.
- [x] 4.4 Run `openspec validate --all --strict`.
- [x] 4.5 Run live smoke through Workbench or Python runner for the selected material/plant.
