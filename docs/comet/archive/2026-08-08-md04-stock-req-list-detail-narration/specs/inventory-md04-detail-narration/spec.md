# Inventory MD04 Detail and Narration Specification

## Purpose

Define the complete target behavior of the `MM.Inventory.GetAvailability` capability: realign its description to the MD04 stock/requirements list, extend its output with MRP element detail lines plus the running available quantity, and keep the AI narrative summary in the existing `narrator` layer grounded in the new detail.

This spec is the complete replacement specification for the capability's read path, fact building, and narration surface. It does not introduce a new capability.

## Domain model

- `MM.Inventory.GetAvailability` - the READ capability (unchanged `capabilityId`, `businessObject:
  InventoryStock`, `bindingId: sap.mm.inventory.md04-stock-req-list`, `rfcName:
  BAPI_MATERIAL_STOCK_REQ_LIST`). READ-only, `sideEffect: none`, no approval.
- `availableQuantity` - scalar running available quantity (existing output, retained). Primary fact.
- `mrpElementLines` - new array output, one entry per MRP element row from `MRP_IND_LINES`. Primary
  fact. Each row carries the MD04 core 5 fields: `mrpElementInd`, `mrpElement`, `elementQty`,
  `availQty1`, `date`.
- `ReasoningFact` (agent) - deterministic fact (`deterministic: true`, `confidence: 1.0`). Its
  `evidence` carries the MRP detail lines. LLM narrative text is never part of `evidence` or
  `primaryFact`.
- `narrator` - existing LLM-grounded narration layer. Inventory guidance is extended to MRP-element
  supply/demand induction; `_SYSTEM_CONSTRAINT` (anti-hallucination) is unchanged; template fallback
  stays deterministic.

## Requirements

### Requirement: Capability description matches the MD04 stock/requirements list

The capability `description`, `aliases`, and `examples` SHALL describe the MD04 stock/requirements
list (MRP element lines + running available quantity), not generic "库存查询". The `capabilityId`,
`businessObject`, `ontologyIri`, `semanticType`, `bindingId`, `rfcName`, and `factTypeRef` SHALL be
unchanged. README capability tables and `agent/README.md` one-liner SHALL use the realigned wording.

#### Scenario: Description realignment preserves identifiers

- **WHEN** the registry is loaded after the change
- **THEN** `MM.Inventory.GetAvailability` resolves with the same `capabilityId`, `businessObject`,
  `bindingId`, and `rfcName` as before
- **AND** its `description` references the MD04 stock/requirements list
- **AND** `aliases` no longer contains the misleading bare "库存查询" alone
- **AND** `openspec validate --all --strict` passes

### Requirement: Capability output carries MRP element detail lines

The capability output SHALL retain `availableQuantity` (scalar, `evidenceRole: primaryFact`) and add
`mrpElementLines` (array, `evidenceRole: primaryFact`). The `executor.outputMapping` SHALL
materialize the `MRP_IND_LINES` table into `mrpElementLines`, with each row carrying `mrpElementInd`,
`mrpElement`, `elementQty`, `availQty1`, and `date`. `executor-bindings.yaml` `allowedOutputs` already
permits `MRP_IND_LINES`; no structural binding change is required.

#### Scenario: MRP_IND_LINES table maps to mrpElementLines rows

- **WHEN** the BAPI returns `MRP_IND_LINES` with N element rows
- **THEN** the execution result `data.mrpElementLines` is an array of N entries
- **AND** each entry has the 5 core fields
- **AND** `data.availableQuantity` is still present as a scalar

#### Scenario: Empty MRP_IND_LINES yields empty detail with scalar preserved

- **WHEN** the BAPI returns no `MRP_IND_LINES` rows but returns a scalar available quantity
- **THEN** `mrpElementLines` is an empty array
- **AND** `availableQuantity` is still present

### Requirement: Fact builder carries MRP detail into evidence

`build_availability_fact` SHALL ingest `mrpElementLines` into `ReasoningFact.evidence` so the detail
is available to the narrator and downstream projection. Existing single-row evidence fields
(`sourceTable`, `sourceField`, `mrpElementInd`, `availableDate`) SHALL remain supported. The fact
stays deterministic (`deterministic: true`, `confidence: 1.0`); LLM narrative text SHALL NOT appear
in `evidence` or as `primaryFact`.

#### Scenario: Detail lines flow into evidence

- **WHEN** an execution result carries `mrpElementLines` with rows
- **THEN** the built `ReasoningFact.evidence` contains the detail rows
- **AND** the fact `value` is the scalar `availableQuantity`
- **AND** no LLM-generated text is present in the fact

### Requirement: Narrator induces over MRP supply/demand elements

The inventory narration guidance SHALL be extended from a single-value conclusion to MRP-element
supply/demand induction, fed by the detail lines in `evidence`. `_build_messages` and the batch
variant SHALL pass the detail lines to the LLM. The `_SYSTEM_CONSTRAINT` anti-hallucination rule
SHALL remain unchanged. The template fallback SHALL remain deterministic and SHALL degrade gracefully
when detail lines are absent (single-value conclusion, as today).

#### Scenario: LLM path receives detail lines

- **WHEN** a fact with MRP detail evidence is narrated and the LLM is available
- **THEN** the LLM prompt includes the detail lines
- **AND** the guidance instructs supply/demand induction within the no-fabrication constraint

#### Scenario: Template fallback without LLM

- **WHEN** the LLM is unavailable
- **THEN** narration falls back to a deterministic template
- **AND** the template does not fabricate values absent from the fact

### Requirement: Frontend projection mirrors the agent fact shape

`inventoryBuilder` SHALL propagate `mrpElementLines` into the projected `ReasoningFact.evidence` so
the frontend snapshot matches the agent fact shape. The builder SHALL still return no fact when
`availableQuantity` is not a finite number (existing guard unchanged).

#### Scenario: Frontend evidence includes detail

- **WHEN** a node fact record carries `mrpElementLines`
- **THEN** the projected inventory fact `evidence` includes the detail rows
- **AND** `value` and `unit` are unchanged from the prior shape

### Requirement: Evals reflect the richer narrative without breaking capability matching

`evals/inventory_availability_cases.yaml` SHALL keep `capabilityId`, validation/execute call counts,
and clarification/failure semantics stable. `responseContains` assertions SHALL be updated to match
the richer narrative. Assertions key on `capabilityId`, not on aliases, so alias realignment SHALL
not change matcher behavior.

#### Scenario: Happy path asserts realigned narrative keys

- **WHEN** the happy-path case runs
- **THEN** the response contains the material, plant, quantity, and unit
- **AND** the matched `capabilityId` is `MM.Inventory.GetAvailability`

## Constraints and invariants

- READ-only: `governance.sideEffect: none`, `requiresApproval: false`, no `BAPI_TRANSACTION_COMMIT`
  or `BAPI_TRANSACTION_ROLLBACK`.
- Fact chain determinism: `deterministic: const true`, `confidence: const 1.0`; LLM narrative never
  becomes `primaryFact`.
- Identifier stability: no rename of `capabilityId`, `businessObject`, `factType`, `bindingId`,
  `rfcName`, or ontology IRIs.
- Anti-hallucination: `_SYSTEM_CONSTRAINT` unchanged; narrator may only use provided fact fields.

## Non-goals

- No identifier/ontology rename (would require a Classic structural migration).
- No change to intent recognition, LLM auth, OData service, PR/PO capabilities.
- No LLM narrative in capability output or fact chain.
- No change to the READ/SAP execution boundary.
