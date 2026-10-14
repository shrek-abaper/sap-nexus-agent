# Ontology Analysis Chat Tool

## ADDED Requirements

### Requirement: Flag-gated DSH registration

The DSH runtime SHALL register `analyze_business_question` only when the server flag `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED` is exactly `1`. Without the flag the registered tool set SHALL be exactly the four semantic tools, and no ontology code path SHALL execute.

#### Scenario: Flag off leaves closed tool surface

- **WHEN** the DSH runtime is built/started without `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED=1`
- **THEN** the tool registry contains `diagnose_material_supply`, `review_customer_exposure`, `review_vendor_exposure`, `propose_replenishment` and does not contain `analyze_business_question`

#### Scenario: Flag on registers the tool

- **WHEN** `SAP_NEXUS_ONTOLOGY_ANALYSIS_ENABLED=1`
- **THEN** `analyze_business_question` is registered with typed parameters `questionType`, `material`, `plant`, `vendor` and the model-facing description states it returns ontology-constrained read analysis only

### Requirement: Typed offline handler with credential-free subprocess

The server handler SHALL invoke the C2 analysis runtime over stdin JSON via an argument-vector subprocess whose environment contains no `SAP_NEXUS_APPROVAL_TOKEN`, `SAP_NEXUS_GATEWAY_URL`, or `SAP_NEXUS_PRINCIPAL`. Inputs SHALL be typed slots; no buildToolQuery/natural-language round-trip SHALL occur.

#### Scenario: Stock question completes offline

- **WHEN** the handler runs with `questionType: "stock-with-unit"`, material DEMOA2, plant 1000
- **THEN** it returns status `complete`, the MD04 stock fact and base unit appear in `facts`, and zero WRITE calls are recorded

#### Scenario: Arrival question reports semantic gap

- **WHEN** the handler runs with `questionType: "arrivals-next-week"`
- **THEN** the response status is `semantic_gap` and the narrative explains no due/receipt fact exists, without claiming arrival quantities

#### Scenario: WRITE question rejected

- **WHEN** the handler runs with `questionType: "create-pr"`
- **THEN** the response status is `rejected` and the narrative states ontology analysis performs no writes

### Requirement: Discriminated response contract

The tool response SHALL carry `kind: "ontology-analysis"` with structured `facts`, analysis `results`, `limitations`, terminal `status` (the C2 seven-value set), and a deterministic Chinese `narrative.summary`. The DSH runtime SHALL use this narrative as the model-facing tool text.

#### Scenario: Runtime renders ontology narrative

- **WHEN** an ontology tool call completes
- **THEN** the model-facing text is exactly `narrative.summary` and no raw structured envelope is passed as the tool text

### Requirement: Three-section chat rendering

`ToolCallCard` SHALL render ontology responses with 事实, 分析, and 限制与缺口 sections and SHALL NOT access semantic-tool-only fields (`capabilityChain`) for them. Existing semantic-tool rendering SHALL remain unchanged.

#### Scenario: Ontology card does not crash and shows sections

- **WHEN** a tool call result has `kind: "ontology-analysis"` with one fact, one grouped result, and one limitation
- **THEN** the card shows the three sections, the grouped measure with unit, and the limitation text

#### Scenario: Semantic tool card unchanged

- **WHEN** a `diagnose_material_supply` result renders
- **THEN** the existing capability chain, facts, and approval UI behave exactly as before
