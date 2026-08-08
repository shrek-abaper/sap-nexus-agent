# Outcome

Realign the `MM.Inventory.GetAvailability` capability so its description matches what
`BAPI_MATERIAL_STOCK_REQ_LIST` (SAP MD04) actually returns, and extend its output from a
single scalar available quantity to the MRP element detail lines plus the running available
quantity. The AI narrative summary stays in the existing `narrator` layer (fact-grounded,
anti-hallucination), now fed by the richer MRP detail so it can summarize supply/demand
elements instead of stating a single number.

# Scope

## Direction A - Description realignment (no identifier changes)

Keep `capabilityId`, `businessObject`, `factType`, `bindingId`, `rfcName` unchanged. Edit only
descriptive text:

- `registry/capabilities.yaml`: `description`, `aliases`, `examples` for `MM.Inventory.GetAvailability`.
- `README.md` capability table row label.
- `README.en.md` capability table row label.
- `agent/README.md` one-line description.

## Direction B - MRP detail lines in capability output + narrator guidance

- `services/gateway/jco/.../InventoryAvailabilityExecutor.java`: the real extraction point. `addMd04StockRowData` currently iterates `MRP_IND_LINES` but returns after the first WB (stock) row, discarding all other supply/demand element rows. Extend it to collect every row into a `mrpElementLines` array (core 5 fields per row: `mrpElementInd`, `mrpElement`, `elementQty`, `availQty1`, `date`), while preserving the existing WB-row `availableQuantity` scalar extraction.
- `registry/capabilities.yaml`:
  - Declare an array output `mrpElementLines` (primaryFact) alongside the retained `availableQuantity` scalar.
  - `executor.outputMapping` retains the `availableQuantity: MRP_IND_LINES.WB.AVAIL_QTY1` declaration (consumed by the Java executor as a routing key, not a literal field path for the array).
- `registry/executor-bindings.yaml`: `allowedOutputs` already includes `MRP_IND_LINES`; no structural change.
- `services/gateway/jco/.../InventoryAvailabilityExecutorTest.java`: extend the MD04 test to assert the `mrpElementLines` array contains all rows (BE + WB), not just the WB scalar.
- `agent/sap_nexus_agent/reasoning_fact.py` `build_availability_fact`: ingest the `mrpElementLines` array into `evidence` (currently only single-row scalars are passed through - `sourceTable`/`mrpElementInd`/`mrpElement`/`availableDate`).
- `agent/sap_nexus_agent/narrator.py`: extend `_INVENTORY_GUIDANCE` from a single-value conclusion to MRP-element supply/demand induction, and extend `_build_messages` / batch variant to feed the detail lines to the LLM within the existing fact-grounded constraint.
- `frontend/src/runtime/projection/fact-builder.ts` `inventoryBuilder`: propagate detail lines into evidence so the frontend projection matches the agent fact shape.
- `evals/inventory_availability_cases.yaml`: update assertions affected by the richer narrative (e.g. `responseContains`), keep capability/id and validation/execute call counts stable.
- `agent/tests/test_reasoning_narrator.py` and related fixtures: cover the new detail-in-evidence path and the updated guidance/messages.

# Non-goals

- Do NOT rename `capabilityId`, `businessObject`, `factType`, `bindingId`, `rfcName`, or any ontology IRI. The 472-reference blast radius is out of scope (would require a Classic structural migration).
- Do NOT change the READ/SAP execution boundary: this stays a READ capability with `sideEffect: none`, no `BAPI_TRANSACTION_COMMIT/ROLLBACK`.
- Do NOT place LLM-generated narrative into capability output / `primaryFact`. The `reasoning-fact.schema.json` `deterministic: const true` / `confidence: const 1.0` invariants forbid non-deterministic text in the fact chain. Narrative stays in `narrator.py`.
- Do NOT change intent recognition, LLM auth, OData service, or PR/PO capabilities.
- Do NOT touch archived specs/runbooks unless a workstream archive is reached.

# Acceptance examples

- A1. `registry/capabilities.yaml` description/aliases/examples describe MD04 stock/requirements list, not generic "库存查询"; identifiers unchanged (`openspec validate --all --strict` passes; registry loader contract test passes).
- A2. Capability output schema carries `availableQuantity` (scalar, primaryFact) + `mrpElementLines` (array, primaryFact); `outputMapping` materializes the `MRP_IND_LINES` table into the array.
- A3. `build_availability_fact` carries the MRP detail lines into `ReasoningFact.evidence`; existing single-row evidence fields still preserved.
- A4. `narrator` inventory guidance/messages pass the detail lines to the LLM and the template fallback remains deterministic; anti-hallucination `_SYSTEM_CONSTRAINT` unchanged.
- A5. Frontend `inventoryBuilder` evidence mirrors the agent fact shape.
- A6. `evals/inventory_availability_cases.yaml` updated assertions pass; agent test suite green.

# Constraints and invariants

- READ-only: no SAP write, no commit/rollback. `governance.sideEffect: none`, `requiresApproval: false`.
- Fact chain stays deterministic: LLM narrative never becomes `primaryFact` / `evidenceRole: primaryFact`.
- Existing factual identifiers stable (see Non-goals).
- Descriptive-text-only edits must not change `capabilityId` matching in evals/matcher (assertions key on `capabilityId`, not aliases).

# Decisions

- D1. Layered architecture: detail lines enter at the capability/fact layer; AI narrative summary stays in the existing `narrator` layer. Rationale: `reasoning-fact.schema.json` constants forbid non-deterministic text in the fact chain; narrator already implements LLM-grounded narration with anti-hallucination + template fallback (per `llm-grounded-narration` design, status final).
- D2. Direction A and Direction B are merged into one Native change.
- D3. `availableQuantity` scalar is retained alongside the new `mrpElementLines` array (convenience + backward compatibility for existing consumers/evals).
- D4. `executor-bindings.yaml` needs no structural change - `allowedOutputs` already permits `MRP_IND_LINES`.
- D5. `mrpElementLines` maps the MD04 core 5 fields per row: `mrpElementInd`, `mrpElement`, `elementQty`, `availQty1`, `date`. Confirmed by user (Q1). Rationale: enough for supply/demand induction in the narrator, minimal contract, least coupling to SAP structure drift.

# Open questions

- [confirmed] CONFIRM: Shared understanding confirmed by user 2026-08-08. Realign `MM.Inventory.GetAvailability` description to MD04 stock/requirements list (Direction A, identifiers unchanged) AND extend its output with `mrpElementLines` (core 5 fields per row) alongside the retained `availableQuantity` scalar (Direction B), with AI narrative summary staying in the existing `narrator` layer fed by the new detail. READ-only unchanged. No identifier/ontology renames.

# Verification expectations

- `openspec list --json && openspec validate --all --strict` (schema/registry).
- `git status --short` before/after.
- Agent test suite covering reasoning_fact + narrator + orchestrator finalize path.
- Frontend `npm --prefix frontend run verify` for the inventoryBuilder change.
- `evals/inventory_availability_cases.yaml` assertions updated and passing.
