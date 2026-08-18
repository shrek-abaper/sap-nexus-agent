# Proposal: declarative-intent-extraction

## Why

The rule-based intent path hardcodes per-capability keyword sets and regex
extractors in Python (`agent/sap_nexus_agent/intent.py`, `pr_intent.py`, and the
sticky-continuation branches in `llm_intent.py`). Every newly registered
capability currently requires new hand-written code before it is visible in
`--intent-mode rule`, which defeats the project's "capability as boundary -
registration, not code" principle and diverges from the already
declaration-driven recall, LLM prompt, and narrator paths.

## What Changes

- Extend the capability registry declaration with intent-extraction metadata:
  `primaryKeywords` (capability trigger), per-input `extraction` matchers
  (keyword/regex/semanticType reference), and per-input `clarifyPrompt`
  (locale-keyed CLARIFY text).
- Add a shared semantic-type extraction catalog (`registry/semantic-types.yaml`)
  defining concept-level matchers (`Plant`, `MaterialNumber`, `Quantity`,
  `Date`, ...) that capabilities reference by `semanticType`, so field-level
  extraction knowledge is defined once and reused.
- Add a generic declaration-driven extraction engine in the agent that replaces
  the hardcoded keyword-scan branches, per-capability builders
  (`_build_inventory_result`, `_build_purchase_order_result`,
  `parse_pr_create_intent`), and the sticky-continuation
  `_extract_params_for`/`_PRIMARY_KEYWORD_SETS` dispatch. The engine has no
  capability-specific branches.
- Make CLARIFY prompts declaration-driven: deterministic template rendering
  from `clarifyPrompt` in rule mode; optional LLM rendering grounded to the
  declared prompt in llm/hybrid modes (LLM may only ask about declared required
  inputs, never invent fields).
- Extend registry contract validation (Python + JSON Schema) to validate
  extraction declarations: regex compile check, backtracking-safety guard,
  `semanticType` reference resolution against the catalog, `clarifyPrompt`
  locale completeness for required inputs.
- Strict behavior parity: all three existing capabilities
  (`MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`,
  `MM.PR.CreateDraft`) are migrated to declaration-driven definitions in this
  change - after migration their extraction behavior is defined solely by
  registry declarations, and the legacy hardcoded path is fully removed.
  Parity constrains only the migration transition: extraction and decision
  results MUST remain identical before and after the switch (no opportunistic
  fixes); `pr_intent.py` is removed and `intent.py` loses its hardcoded
  keyword sets and extractors.

## Capabilities

### New Capabilities

- `declarative-intent-extraction`: declaration-driven intent extraction -
  registry extraction declarations, shared semantic-type extraction catalog,
  generic extraction engine, and declaration-driven CLARIFY rendering, such
  that a capability registered with extraction declarations is fully usable in
  rule mode without agent code changes.

### Modified Capabilities

- `registry-ontology-contract`: the registry contract validator gains
  requirements for extraction declaration validation (matcher schema,
  `semanticType` catalog reference resolution, regex compile/backtracking
  guards, `clarifyPrompt` locale completeness) and for the new
  `registry/semantic-types.yaml` catalog contract.

## Impact

- **Registry**: `registry/capabilities.yaml` (three existing capabilities gain
  extraction declarations with strict-parity values),
  new `registry/semantic-types.yaml`.
- **Schemas/validator**: `schemas/` JSON Schema for extraction declarations and
  the semantic-type catalog; `scripts/validate-registry-contract.py` rules.
- **Agent**: `agent/sap_nexus_agent/` - `intent.py` (hardcoded branches ->
  engine dispatch), `pr_intent.py` (removed), `llm_intent.py`
  (sticky-continuation extraction -> engine dispatch; CLARIFY LLM rendering
  hook), `registry_loader.py` (load extraction declarations + catalog),
  new extraction engine module.
- **Gateway**: no runtime behavior change; extraction declarations are
  agent-side metadata the gateway loader may ignore or pass through.
- **Tests/evals**: existing agent tests (1145 passed baseline) and call-plan
  eval must stay green unchanged; new tests cover the engine, validator
  rejections, and a fixture capability that is rule-mode usable via
  declaration only.
- **Risk**: regex becomes managed data - mitigated by load-time compile
  validation and backtracking guards; semantic drift during migration -
  mitigated by strict parity tests and per-capability migration steps.
