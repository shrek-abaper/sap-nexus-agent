# Outcome

Generalize the narrator from per-capability hardcoded branches to a factShape-clustered, metadata-driven framework. Adding a capability's narration should require only a `narrative` declaration in `capabilities.yaml` (factShape + templates + fieldMapping + detailFormatter), not new Python entry points, prompt builders, or template fallbacks.

# Scope

## Four layers to generalize

1. **guidance** (`narration_guidance`): already metadata-driven by businessObject; fold into the new `narrative` declaration.
2. **prompt construction** (`_build_messages` / `_build_po_messages` / `_build_inventory_batch_messages`): per-capability hardcoded field names -> generic fieldMapping from fact fields to template variables.
3. **template fallback** (`_template_inventory` / `_template_po` / `_template_inventory_batch`): per-capability hardcoded -> generic fallbackTemplate + pluggable detailFormatter.
4. **orchestrator dispatch** (`_finalize_inventory` / `_finalize_purchase_order` / `_finalize_pr_create` + `if capability_id == INVENTORY` branching): per-capability -> unified dispatch by `narrative.factShape`.

## Schema extension

- `schemas/capability.schema.json`: add optional `narrative` object on each capability:
  - `factShape`: `single-value` | `list` | `action-receipt`
  - `promptTemplate`: template id (references a centralized prompt template)
  - `fallbackTemplate`: template id (deterministic LLM-unavailable output)
  - `fieldMapping`: fact fields -> template variables
  - `detailFormatter`: `mrp-table` | `po-list` | `none` (pluggable detail renderer)
- `registry/capabilities.yaml`: each of the 3 existing capabilities gets a `narrative` declaration.

## Narrator convergence

- `narrator.py`: 3 generic entry points by factShape:
  - `narrate_single_value(fact, narrative_config)`
  - `narrate_list(facts, narrative_config)`
  - `narrate_action_receipt(fact_or_result, narrative_config)`
- Each entry: fieldMapping fills template vars; detailFormatter renders detail; LLM path appends deterministic detail table; fallback uses fallbackTemplate.
- Detail formatters (`mrp-table`, `po-list`, `none`) are pluggable functions keyed by id.

## Orchestrator convergence

- Unified `_finalize_narrative` dispatches by `narrative.factShape` from the capability descriptor, replacing the 3 `_finalize_*` branches.
- PR create (currently bypasses narrator, f-string in orchestrator) must be brought into the framework: needs a fact builder + `action-receipt` narrative declaration.

## Frontend

- `frontend/src/runtime/projection/fact-builder.ts`: inventoryBuilder detail mirroring already done; no change expected unless action-receipt shape needs projection.
- `frontend` `CapabilityDescriptor` / registry loader TS types may need `narrative` field if they mirror the registry.

# Non-goals

- Do NOT change the fact-chain determinism invariant: `reasoning-fact.schema.json` `deterministic: const true` / `confidence: const 1.0`; LLM narrative never in `evidence`/`primaryFact`.
- Do NOT change intent recognition, LLM auth, OData service, or SAP execution paths.
- Do NOT rename existing `capabilityId`/`businessObject`/`factType`/`bindingId` identifiers.
- Do NOT change the READ/WRITE boundary or approval gating.
- Do NOT introduce a new capability; only refactor narration for the 3 existing ones.
- Do NOT auto-generate narrative declarations for future capabilities (out of scope; the framework enables it but doesn't automate).

# Acceptance examples

- A1. `capability.schema.json` validates a capability with a `narrative` block; `openspec validate --all --strict` passes.
- A2. Each of the 3 existing capabilities has a `narrative` declaration with the right factShape.
- A3. `narrator.py` has 3 generic entry points by factShape; no per-capability `narrate_fact`/`narrate_purchase_order_facts` hardcoded field logic remains.
- A4. Orchestrator dispatches by `narrative.factShape`; no `if capability_id == INVENTORY` branching.
- A5. PR create narration goes through the framework (action-receipt), not an orchestrator f-string.
- A6. Adding a hypothetical 4th capability's narration requires only a `narrative` declaration, zero new narrator/orchestrator code (verified by a test that registers a synthetic capability with a narrative declaration and narrates it).
- A7. Existing inventory (single-value + mrp-table detail) and PO (list + po-list detail) output is behavior-preserving (eval 7/7, agent tests green).
- A8. detailFormatter is pluggable: `mrp-table`, `po-list`, `none` render correctly; unknown formatter falls back to `none`.

# Constraints and invariants

- Fact-chain determinism: LLM narrative never becomes `primaryFact`/`evidence`; `_SYSTEM_CONSTRAINT` anti-hallucination unchanged.
- Behavior preservation: existing inventory/PO narrative output formats (structured MD04 table, PO list) must not regress.
- Identifier stability: no rename of capabilityId/businessObject/factType/bindingId.
- READ/WRITE boundary and approval gating unchanged.

# Decisions

- D1. factShape clusters by fact data shape, not businessObject: `single-value` (inventory), `list` (PO), `action-receipt` (PR create). Rationale: same businessObject can have different shapes (inventory single vs batch); shape drives the narration pipeline.
- D2. `narrative` declaration lives inline in `capabilities.yaml` (not a separate yaml). Rationale: co-located with the capability; one file to edit; registry snapshot covers it.
- D3. detailFormatter is a pluggable Python function keyed by id (`mrp-table`/`po-list`/`none`), registered in a formatter registry. New formatters need code, but no new narration pipeline. Rationale: pure formatting can't be pure config.
- D4. PR create (action-receipt) must be brought into the framework: needs a fact builder (`build_pr_create_fact`) + `action-receipt` narrative declaration. Currently bypasses narrator entirely. Confirmed by user (Q1): include in this change.
- D5. `promptTemplate`/`fallbackTemplate` are template IDs referencing a centralized template registry in `narrator.py` (not inline strings in capabilities.yaml). Rationale: keeps capabilities.yaml declarative; template text is Python-adjacent code that benefits from version control alongside narrator; avoids YAML multiline string escaping. Implementation choice, not user-visible.
- D6. `fieldMapping` maps both `ReasoningFact` fixed fields (material/plant/value/unit) and `evidence[0]` dynamic fields (mrpElementLines/purchaseOrder/...) to template variables. Implementation choice.

# Open questions

- [confirmed] CONFIRM: Shared understanding confirmed by user 2026-08-08. Generalize narrator from per-capability hardcoded branches to a factShape-clustered (single-value/list/action-receipt) metadata-driven framework. PR create action-receipt is included (new fact builder + narrative declaration). narrative declaration inline in capabilities.yaml; prompt/fallback templates are IDs referencing a centralized template registry in narrator.py; fieldMapping covers fact fixed fields + evidence dynamic fields; detailFormatter pluggable (mrp-table/po-list/none). Goal/scope/key decisions/acceptance/non-goals as written above.

# Verification expectations

- `openspec validate --all --strict` (schema/registry).
- `git status --short` before/after.
- Agent test suite: narrator + orchestrator + reasoning_fact + registry contract + workbench output.
- `evals/inventory_availability_cases.yaml` 7/7 + `evals/matcher_cases.yaml` snapshotId sync.
- Frontend `npm --prefix frontend run verify` if TS types mirror the registry.
- A synthetic-capability test proving zero-code narration (A6).
