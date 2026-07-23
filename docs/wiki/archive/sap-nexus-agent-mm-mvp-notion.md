# SAP Nexus Agent MM MVP - Notion Knowledge Import

Source: `https://app.notion.com/p/SAP-Nexus-Agent-BAPI-RFC-SAP-MM-MVP-1d35381207a741a0a879b49eac03cd0c`

Imported: 2026-06-18

## 1. Positioning

`SAP Nexus Agent` is intended as a capability-ontology-driven SAP closed-loop agent, not only an inventory query bot.

The first MVP scenario is **MM inventory awareness and procurement planning suggestions**. It validates whether SAP business objects, BAPI/RFC capabilities, deterministic rules, LLM reasoning, human confirmation, and execution feedback can be connected into an auditable loop.

Core loop:

```text
Sense -> Analyze -> Decide -> Act -> Feedback
```

## 2. Phase Boundaries

### Phase 1 - Read

Goal: natural language inventory questions become controlled read capability calls, then return structured results plus narrative explanation.

Initial inventory scenarios:

1. Query stock and availability by `material + plant`.
2. Query stock detail by `material + plant + storage location`.
3. Optionally support batch, special stock, and controlled stock lists with pagination and performance limits.

Phase 1 deliverables:

- `Capability Registry` with 2-5 whitelisted inventory read capabilities.
- `Query/Call Plan` schema.
- Narrative templates for field semantics and result interpretation.
- Regression set with 50-100 realistic utterances, including ambiguity, missing parameters, and invalid IDs.
- Runtime guardrails: rate limiting, timeout, default scope, audit logs.

Suggested success indicators:

- Capability selection accuracy >= 95%.
- Parameter completion and validation pass rate >= 90%.
- Explanation readability and parameter consistency >= 95%.

### Phase 2 - Reasoning

Goal: evidence-driven reasoning on top of read results, without expanding the read surface too quickly.

Reasoning examples:

- Consistency checks.
- Risk hints.
- SAP field semantics explanation.
- BOM expansion from finished goods to raw material requirements.
- Net demand reasoning from stock, in-transit stock, open PO, safety stock, MOQ, lot size, and lead time.
- Procurement plan suggestions with explicit evidence and uncertainty.

Hard constraint: every conclusion must cite evidence fields from read results. Missing fields should trigger secondary read suggestions only within the whitelist.

### Phase 3 - Action With Human In The Loop

Goal: convert reasoning into action proposals, ask for human confirmation, then execute write capabilities through BAPI/RFC.

Write capabilities are explicitly out of Phase 1. Future write support must include:

- Write capability whitelist.
- Deterministic validators.
- Human confirmation showing capability, key parameters, impact, reversibility, and risk.
- End-to-end audit with confirmer, timestamp, SAP `RETURN`, object ID, and failure reason.

## 3. Technical Direction

Main execution path: **BAPI/RFC through Java JCo Gateway**.

Python + LLM agent responsibilities:

- Intent routing.
- Capability selection.
- Parameter building.
- Deterministic validation orchestration.
- Narration and explanation.

Java JCo Gateway responsibilities:

- Destination pool.
- RFC metadata resolver.
- Type converter.
- Whitelisted BAPI/RFC execution.
- `RETURN` message normalization.
- Audit logging integration.

Explicitly avoid exposing raw `rfcName + arbitrary parameters` to the LLM.

Correct execution model:

```text
LLM -> capabilityId -> Validator -> Java JCo Gateway -> whitelisted RFC/BAPI -> SAP
```

Recommended gateway endpoints:

```text
POST /capabilities/{capabilityId}/validate
POST /capabilities/{capabilityId}/execute
```

`ADT run_sql` can be a supplemental executor for analytical queries, verification, or field gaps, but only with strong guardrails. Direct HANA access is optional and not the main path.

## 4. Capability Ontology And Registry

The plan shifts the semantic layer from table-field semantics to **BAPI/RFC capability semantics**.

Core model:

- `Capability`: a callable read/write capability mapped to a standard BAPI or customer RFC.
- Attributes: inputs, outputs, field semantics, constraints, permissions, performance risk, audit tags.
- Relationships: covered business object, complements, join keys, preconditions, side effects.

Recommended storage strategy:

```text
OWL = semantic source of truth
YAML / JSON Registry = execution source of truth
Runtime DB = fact and audit source of truth
```

MVP should be **OWL-centered**, not GraphDB-first:

- Use OWL files for semantic classes and relationships.
- Use YAML/JSON registry for `capabilityId`, `rfcName`, parameter schema, variants, limits, and audit tags.
- Use JSON Schema / Pydantic for deterministic validation.
- Use Runtime DB for call plans, traces, audits, and eval results.

Suggested registry example anchor:

```yaml
capabilityId: MM.Inventory.GetStockByMaterialPlant
ontologyIri: "sapnexus:MM_Inventory_GetStockByMaterialPlant"
type: READ
executor:
  type: RFC
  rfcName: BAPI_MATERIAL_STOCK_REQ_LIST
```

## 5. Domain Expansion Path

Inventory is the first state foundation for procurement planning:

```text
FinishedGood --explodes_to--> RawMaterial
ProductionPlan --generates--> Requirement
Requirement --consumes--> InventoryStock
Requirement --covered_by--> OpenPO / OpenPR / InTransitStock
InventoryStock --located_at--> Plant / StorageLocation / Batch
RawMaterial --supplied_by--> Supplier
Supplier --has--> LeadTime
TransportationRisk --adjusts--> ProcurementProposal
Shortage --triggers--> ProcurementProposal
ProcurementProposal --confirmed_as--> PR / PO
```

The architecture should later support procurement planning, sales fulfillment, production planning, master data governance, and other SAP scenarios, but Phase 1 should stay focused on MM inventory read capability.

## 6. Open Questions For Local Design

1. Which runtime should this repository host first: Python orchestrator only, Java JCo Gateway only, or a small monorepo with both?
2. What SAP connectivity is available for MVP validation: real JCo, mocked gateway, ADT SQL, or recorded fixtures?
3. Which exact Phase 1 capability should be the first vertical slice: stock by material/plant, storage-location detail, or availability/ATP?
4. Should OWL be executable in the first slice, or should the first slice use YAML registry with OWL skeleton checked in but not loaded?
5. What is the minimum audit store for MVP: local SQLite, file-based JSONL, or an existing service/database?
6. Does the first demo need an API-only flow, CLI flow, or lightweight UI/chat surface?

## 7. Recommended First Change Scope

Create one narrow vertical slice:

```text
Natural language query
-> intent/capability selection
-> validated call plan
-> mocked or real Java JCo Gateway read execution
-> normalized stock result
-> narrative explanation
-> audit trace
```

Suggested non-goals for the first change:

- No write BAPI execution.
- No automatic PR/PO creation.
- No GraphDB/RDF store.
- No broad BI aggregation or trend analytics.
- No unrestricted RFC or SQL execution.

