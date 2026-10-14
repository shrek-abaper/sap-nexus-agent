---
comet_change: ontology-goal-read-analysis
role: technical-design
canonical_spec: openspec
archived-with: 2026-10-14-ontology-goal-read-analysis
status: final
---

# Design Doc — Ontology-Goal Dynamic Read Analysis (C2)

Deep technical refinement of `openspec/changes/ontology-goal-read-analysis/design.md` (ADR-1..9, user-confirmed in C0). Consumes the archived C1 `semantic-release-package` (module `sap_nexus_agent.semantic_release`, artifact `ontology/generated/semantic-release.json`).

## 1. End-to-end flow

```text
typed request (CLI stdin / TS coordinator)
  │  {schemaVersion:1, requestId, slots{...}, scope, interpreter:"fake"|"model"}
  ▼
GoalInterpreter ── fake: fixture-scripted ; model: Protocol only (no impl)
  │  SemanticGoalDraft v1 (UNTRUSTED)
  ▼
draft_validation ── strict JSON Schema + deep technical-key scan + bounds ── reject
  ▼
release.pin: build_semantic_release(repo_root); dual-id association verify
  ▼
GoalResolver (visible READ cards from discover_cards + C1 allowlist/object catalog)
  │  ResolvedGoal  │  CLARIFY / CAPABILITY_GAP / SEMANTIC_GAP / AMBIGUOUS_PRODUCER
  ▼
SemanticCompiler ── validate_plan_graph_v2(readPlan) + analysis DAG validation
  │  ValidatedReadAnalysisPlan (server-owned, READ_ONLY, actionPartition=[])
  ▼
read execution
  ├─ Python CLI path: FakeGatewayClient (evals fixtures) → NodeResult[]
  └─ TS path: PlanExecutor + GatewayClient (FakeGateway in tests) → NodeResult[]
  ▼
analysis_runtime subprocess boundary  (Python is the ONLY math authority)
  │  stdin wire v1 → normalize (allowlist) → four operators → AnalysisResult[]
  ▼
EvidenceResponse v1 {facts, results, exclusions, statuses, uncoveredConclusions, evidence}
```

## 2. Versioned contracts (Python frozen dataclasses + JSON Schemas)

All dataclasses live in `ontology_planning/contracts.py`, frozen, with explicit `to_dict()`/`from_dict()`; JSON is camelCase. Four new schemas under `schemas/`, all draft 2020-12, recursive `additionalProperties:false`.

### 2.1 SemanticGoalDraft v1 — `schemas/semantic-goal-draft.schema.json`

```json
{
  "schemaVersion": 1,
  "requestedFacts": [
    {"factTypeId": "sapnexus:PurchaseOrderSupplyFact",
     "fields": ["orderQuantity", "supplier", "purchaseOrderUnit"],
     "objectSelectors": [{"objectTypeId": "sapnexus:Material", "key": "material", "value": "DEMOA2"},
                         {"objectTypeId": "sapnexus:Plant", "key": "plant", "value": "1000"}]}
  ],
  "constraints": [
    {"name": "supplier", "semanticType": "sapnexus:Supplier", "value": "V72719",
     "source": "explicitUser"}
  ],
  "analysisNodes": [
    {"nodeId": "a1", "operatorId": "group_sum",
     "inputs": [{"kind": "factField", "factTypeId": "sapnexus:PurchaseOrderSupplyFact",
                 "field": "orderQuantity"}],
     "params": {"dimensions": ["supplier"], "unitField": "purchaseOrderUnit"},
     "dependsOn": []}
  ],
  "requestedConclusions": [
    {"id": "c1", "statement": "PO quantities grouped by supplier next to current stock",
     "evidenceRequirement": "per-row lineage, units explicit"}
  ],
  "assumptions": ["plant scope inherited from confirmed context only"]
}
```

- `constraints[].source` closed enum: `explicitUser | confirmedContext`; draft-claimed context is downgraded/ignored unless the server confirms it.
- Deep technical-key scan: key names matching `rfc|binding|url|credential|token|secret|password|sql|query|path|import|exec|eval|script|command` and string values matching `BAPI_[A-Z_]+`, `https?://`, `[A-Za-z]:\\`, `/^[./]/`, shell metacharacter patterns → `DRAFT_TECHNICAL_KEY` rejection. Scanning is recursive over dict/list; any depth.
- Bounds enforced on the draft itself: ≤6 requested facts, ≤6 analysis nodes, nesting depth ≤8, total JSON ≤256 KiB, strings ≤4 KiB, numbers must be finite (JSON parser rejects NaN/Infinity by default; `parse_constant` raises).
- Field/operator IDs are NOT schema-enums; they resolve against the pinned release in the resolver (schema-only typos must not be confused with release drift).

### 2.2 ReadAnalysisPlan v1 — `schemas/read-analysis-plan.schema.json`

```json
{
  "schemaVersion": 1,
  "planId": "sha256:<server-generated>",
  "semanticSnapshotId": "sha256:...",
  "registrySnapshotId": "sha256:...",
  "principalId": "local-user-0001",
  "scope": {"plant": "1000"},
  "readPlan": { "planGraphVersion": 2, "executionMode": "READ_ONLY",
                "actionPartition": [], "nodes": [], "edges": [] },
  "analysisPlan": {
    "nodes": [{"nodeId": "a1", "operatorId": "group_sum",
               "inputs": [{"kind":"factField"|"nodeRef", ...}],
               "params": {}, "definitionRefs": [], "dependsOn": []}],
    "outputs": ["a1"]
  },
  "limits": {"maxReadNodes": 6, "maxAnalysisNodes": 6, "maxDepth": 4,
             "overallTimeoutSeconds": 90, "maxRows": 5000, "maxResponseBytes": 2097152},
  "freshness": {},
  "coverage": {"covered": ["c1"], "uncovered": [{"conclusionId": "c2", "reason": "SEMANTIC_GAP:..."}]}
}
```

- `readPlan.executionMode` const `READ_ONLY`; `readPlan.actionPartition` const `[]`; every node capability must be visible active READ.
- No client-writable verified/authorization fields exist in the schema; planId/ids are server-set. Schema rejects any client attempt structurally.

### 2.3 TypedFact v1 — `schemas/typed-fact.schema.json`

```json
{"schemaVersion": 1, "factId": "node-2:row:7",
 "factTypeRef": "sapnexus:PurchaseOrderSupplyFact",
 "objectType": "PurchaseOrderItem",
 "objectKey": {"purchaseOrder": "4500000001", "purchaseOrderItem": "00010"},
 "scope": {"plant": "1000"},
 "rowIdentity": {"purchaseOrder": "4500000001", "purchaseOrderItem": "00010"},
 "fields": {"orderQuantity": {"value": "100.000", "semanticType": "sapnexus:Quantity"},
            "purchaseOrderUnit": {"value": "EA", "semanticType": "sapnexus:UnitOfMeasure"}},
 "unit": {"field": "purchaseOrderUnit", "value": "EA"},
 "businessTime": null, "collectedAt": "2026-10-14T00:00:00Z",
 "definitionRef": null,
 "evidence": {"runId": "...", "nodeId": "node-2", "gatewayTraceId": "...",
              "rawFields": ["purchaseOrder","purchaseOrderItem","orderQuantity","purchaseOrderUnit"],
              "completeness": "complete"}}
```

- Numeric measure values are carried as **decimal strings** in facts and results (never JSON numbers for measures) so Decimal semantics survive the wire.
- `completeness`: `complete | incomplete:truncated`; `definitionRef` is `null` or a grounded applicable Definition id (v1 applicability list is empty → always null).
- Row identity duplicates across one fact type within one run → `ROW_IDENTITY_CONFLICT`; rows stay in the record, aggregation over that fact type is blocked and reported.

### 2.4 AnalysisResult v1 — `schemas/analysis-result.schema.json`

```json
{"schemaVersion": 1, "nodeId": "a1", "operatorId": "group_sum", "status": "complete",
 "outputType": "groupedRows",
 "rows": [{"groupKey": {"supplier": "V72719"},
           "measures": {"orderQuantity": {"decimal": "250.000", "unit": "EA"}},
           "lineage": [{"factId": "node-2:row:7"}, {"factId": "node-2:row:8"}]}],
 "excludedRows": [{"factId": "node-2:row:9", "reason": "MISSING_UNIT"}],
 "operatorVersion": "0.1.0", "definitionRefs": [],
 "partial": false, "limits": {}}
```

- `status` closed enum: `complete | partial | clarification | capability_gap | semantic_gap | rejected | failed`.
- `compare` rows require `caliberRef` compatibility (both sides share semantic kind + unit + allowed time-point policy defined per operator catalog constraints); otherwise the node result is `semantic_gap` with reason code `INCOMPATIBLE_COMPARISON`.

## 3. Module responsibilities and key APIs

| Module | Public surface |
|---|---|
| `contracts.py` | dataclasses + to_dict/from_dict for the four documents; `STATUS_*` constants |
| `bounds.py` | `BOUNDS: Bounds` frozen constants (readNodes 6, analysisNodes 6, depth 4, modelTurns 2, timeoutSeconds 90, maxRows 5000, maxResponseBytes 2 MiB, draftBytes 262144) |
| `draft_validation.py` | `validate_draft(doc: dict, release: SemanticReleasePackage) -> DraftValidationReport`; issues carry codes `DRAFT_SCHEMA_*`, `DRAFT_TECHNICAL_KEY`, `DRAFT_BOUNDS`, `DRAFT_UNKNOWN_FIELD`, `DRAFT_UNKNOWN_OPERATOR`, `DRAFT_DAG_CYCLE`, `DRAFT_UNRESOLVED_INPUT` |
| `interpreter.py` | `GoalInterpreter` Protocol (`interpret(request, vocabulary) -> SemanticGoalDraft`); `FakeGoalInterpreter(cases_dir)` |
| `release.py` | `pin_release(repo_root, expected_registry_id=None) -> PinnedRelease`; loads semantic-release.json **and** rebuilds in memory, failing on any byte/id mismatch; exposes assets + package |
| `resolver.py` | `resolve(draft, pinned, cards, principal) -> Resolution` returning `ResolvedGoal` or typed terminal outcome; producer search uses cards filtered by active/Function/sideEffect none/approval false; ambiguity lists candidates; derivation via `derive_data_dependencies` |
| `compiler.py` | `compile(resolved, pinned) -> ReadAnalysisPlan | CompilerFailure`; authors read nodes (its own `_author_read_node`, mirroring the v2 node dict contract) and analysis DAG; calls `validate_plan_graph_v2`; planId = sha256 over canonical plan |
| `fact_normalizer.py` | `normalize(node_results, pinned) -> list[TypedFact]`; field map derived solely from the C1 allowlist; PO header/items expansion with header fallback (parity rules taken from TS fact-builder, see §6) |
| `operators.py` | Four pure functions over TypedFact lists returning AnalysisResult rows; Decimal; lineage lists |
| `analysis_runtime.py` | `run(analysis_plan, facts, pinned) -> list[AnalysisResult]`; module CLI stdin/stdout wire entry (§5) |
| `fake_gateway.py` | `FakeGatewayClient(cases_dir, case_id)` implementing validate/execute over fixture files; call log for zero-WRITE assertions |
| `coordinator.py` | `run_analysis(request, repo_root, cases_dir=None) -> EvidenceResponse`: pin → interpret(fake) → validate draft → resolve → compile → execute (fake) → normalize → analyze → render evidence envelope |
| `cli.py` | `-m sap_nexus_agent.ontology_planning.cli --case <id> | --request-file <path> [--repo-root] [--json]`; exit 0 with typed terminal statuses; exit 3 on rejected draft |

### Resolver outcome model

```python
class ResolutionStatus(StrEnum):  # values reused verbatim in EvidenceResponse
    RESOLVED = "complete"
    CLARIFICATION = "clarification"
    CAPABILITY_GAP = "capability_gap"
    SEMANTIC_GAP = "semantic_gap"
    AMBIGUOUS_PRODUCER = "clarification"  # ambiguity is a clarify subclass at response level
    REJECTED = "rejected"
```

A semantic gap is produced structurally when a requested field is absent from the allowlist (Q5 arrival/receipt fields) or when a conclusion requires fact types no registered fact provides (Q6 demand). Inventory conclusions are caliber-limited: the renderer may only use the MD04 snapshot label; any `ATP|available to promise|promised|guaranteed` phrasing keyed on inventory is a renderer-side violation covered by a negative test asserting the response contains no ATP vocabulary for inventory answers.

### WRITE defense layers (all four required)

1. resolver producer predicate excludes non-READ (test: PR capability invisible to search);
2. compiler asserts every read node governance `requiresApproval=false`, `sideEffect=none`, and `readPlan.actionPartition == []`;
3. analysis DAG inputs may only reference facts/nodes — capability ids are not valid input kinds;
4. execution gate: FakeGatewayClient/TS coordinator refuse non-READ capability ids; tests assert call-log zero WRITE for direct, nested-derived, and analysis-disguised drafts.

## 4. Release pinning

`release.pin_release` rebuilds via `build_semantic_release(repo_root)` and compares with the tracked `ontology/generated/semantic-release.json` byte-for-byte (this reuses the C1 `--check` invariant, so a stale package fails before planning). The plan stores both ids; each NodeResult/TypedFact/AnalysisResult echoes `semanticSnapshotId`. In-flight pinning is process-local immutability for C2 (single CLI/request process); TS coordinator pins once per run and passes the ids into the child. No cache service is built in C2.

## 5. TS↔Python wire contract v1

`python -m sap_nexus_agent.ontology_planning.analysis_runtime` (adapter builds args, never shell strings):

stdin:
```json
{"wireVersion": 1,
 "release": {"semanticSnapshotId": "sha256:...", "registrySnapshotId": "sha256:..."},
 "nodeResults": [{"nodeId": "node-2", "capabilityId": "MM.PurchaseOrder.GetList",
                  "parameters": {"material": "DEMOA2", "plant": "1000"},
                  "gatewayTraceId": "fake-1", "executedAt": "...", "data": { ...raw... }}],
 "analysisPlan": { ... §2.2 analysisPlan... },
 "requestedConclusions": [ ... ]}
```
stdout:
```json
{"wireVersion": 1, "status": "complete|partial|...",
 "facts": [TypedFact...], "results": [AnalysisResult...],
 "uncoveredConclusions": [{"conclusionId": "c2", "reason": "..."}],
 "limits": {...}, "semanticSnapshotId": "sha256:..."}
```

- Adapter (`python-analysis-adapter.ts`): spawn with arg vector, stdin JSON, AbortSignal timeout at BOUNDS.overallTimeoutSeconds, env constructed with **deletion** of `SAP_NEXUS_*` credential/gateway vars and no gateway URL; logs redact `data` payloads.
- stdout must validate against an inline TS mirror of the response shape; non-JSON/schema-invalid → typed `failed` result, no partial adoption.
- Size guard: reject spawn when input > maxResponseBytes.

`frontend/src/runtime/dynamic-analysis/types.ts` holds the TS wire types (no import from python). `coordinator.ts` depends on PlanExecutor types and GatewayClient only; it must not import composition/*, recommendation/*, projection/* modules.

## 6. Normalization rules (single source of truth: Python)

PO payload handling matches the proven TS rules (frontend/src/runtime/projection/fact-builder.ts):
- each top-level purchaseOrders entry is a header; `items[]` present → one row per item with header fallback for absent item fields; absent `items[]` → one row from the header;
- `orderQuantity` taken from item if present else header; finite decimal only (regex decimal or number; NaN/Inf → row excluded `NON_FINITE_MEASURE`);
- material/plant fall back to node parameters; rows sorted deterministically by identity key;
- duplicate row identity within one node → conflict marker, rows retained, aggregation blocked for that fact type;
- inventory node: `availableQuantity` scalar → one TypedFact; `mrpElementLines` stays opaque (never enters fields);
- material node: scalar fields one TypedFact per key.

## 7. Fixture layout and case contract

```
evals/ontology-read-analysis/
  cases.json            # 24 dev cases (array; see below)
  gateway/<case-id>/<node-index>-<capabilityId>.json   # raw execute data payloads
  holdout/              # sealed: README + .gitkeep in C2; real cases added only by user in C3
```

Case entry:
```json
{"id": "q2-po-group-by-supplier",
 "kind": "positive|negative",
 "request": {"slots": {"material": "DEMOA2", "plant": "1000"}},
 "draftFixtureFile": "drafts/q2.json",      // fake interpreter output
 "expect": {"status": "complete",
            "capabilities": ["MM.Inventory.GetAvailability","MM.PurchaseOrder.GetList"],
            "readMode": "READ_ONLY", "actionPartition": [],
            "analysisOperatorIds": ["select_fields","group_sum"],
            "writeGatewayCalls": 0,
            "gaps": [],
            "assertions": ["total-EA-V72719=250.000 EA", "lineageRows>=2",
                           "renderHasNo:ATP"]}}
```

Negative-case gap assertions use codes (`MISSING_SELECTOR_VALUE`, `NO_PRODUCER:*`, `AMBIGUOUS_PRODUCER:*`, `FIELD_NOT_ALLOWLISTED:*`, `INCOMPATIBLE_COMPARISON`, `MISSING_UNIT`, `ROW_IDENTITY_CONFLICT`, `TRUNCATED`, `WRITE_REJECTED`). Assertion predicates are a tiny fixed interpreter (no eval/arbitrary expressions): `key=value`, `key>=n`, `renderHas:word`, `renderHasNo:word`, `factFieldAbsent:<field>`.

24 dev cases per tasks.md group 11; holdout harness runs any `holdout/cases-*.json` when present and fails closed if a case id appears referenced from non-test code (grep-based test).

## 8. CLI and evidence envelope

CLI stdout (`--json`) is the EvidenceResponse: request echo (slots only), draft validation issues, plan (read + analysis), release ids, node execution records (params, trace ids, raw-field names, not secrets), TypedFacts, AnalysisResults with lineage, exclusions+reasons, per-conclusion coverage, overall status, `notRun: ["SAP live","paid model","chat"]`. Non-json mode prints a deterministic text template with sections Facts / Analysis / Gaps / Limits. Exit codes: 0 success or typed non-rejected terminal status; 3 rejected draft; 2 usage; 1 internal failure.

## 9. Bounds and configuration

`bounds.py` constants only in v2; no request- or model-provided overrides. Any change to bounds is a compiler semantics change → bump `compilerVersion` in `ontology/analysis-versions.yaml` (covered by C1 semanticSnapshotId) in the same change; a test asserts the file version is referenced by the pinned release. Timeout applies to the TS child spawn and to Python fake execution (wall-clock budget; fixtures make it nominal).

## 10. Test strategy

- Python: one pytest module per ontology_planning module; red-green per task; property/parity tests: PO normalization parity vs TS fixture expectations, determinism of planId/results across runs, per-case contract runner over all 24 cases, zero-WRITE call log, draft scanner corpus, wire schema round trips.
- TS: vitest for adapter (env sanitization assertion, invalid stdout fail-closed, timeout) and coordinator (FakeGateway end-to-end Q1/Q2/Q3/Q7, release mismatch fail-closed, partial failure isolation). Run `npm --prefix frontend run verify`.
- Legacy regression: v2 compiler, derivation, semantic planning, contract, TS plan-executor/composition/semantic-tools suites must remain green; no edits to legacy modules (compiler authors its own nodes; verify by import-graph test that ontology_planning imports no private `_build_node_v2`).
- Offline evidence: CLI run for representative cases with network disabled env.

## 11. Risks / mitigations

- Node-shape drift from PlanGraph v2 → compile every test plan through `validate_plan_graph_v2` and the JSON schema; no local relaxed validator.
- Decimal loss over wire → decimal strings + a test failing on numeric measure fields.
- Fixture duplication between languages → single evals directory; TS tests resolve repoRoot via existing `SAP_NEXUS_AGENT_ROOT`/relative convention.
- Fake interpreter tests masquerading as quality evidence → every report labels them contract evidence; holdout sealed.
- Importing composition/recommendation by accident → import-graph lint test on dynamic-analysis/*.ts.

## 12. Rollback

All new files (package, schemas, TS directory, fixtures, CLI); no legacy/WRITE/Java changes; feature unreachable from chat. Revert removes the feature entirely; C1 package remains independently valid (it ships no consumers after revert).
