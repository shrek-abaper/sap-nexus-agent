# Design: declarative-intent-hardening

## Context

The registry contract (v2 capabilities + v1 semantic-type catalog) is about to
freeze. Today matchers are free regex (semantic-types.yaml), clarify prompts
enumerate missing-set combinations, and extraction blocks assume a single
text source (`resolver: text`). The extraction engine
(`agent/sap_nexus_agent/extraction/`) reads these declarations through
`registry_loader.py`; `scripts/validate-registry-contract.py` validates them
against `schemas/*.schema.json`. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**

- B1: named matcher kinds + `valueShapes` + justified-regex escape hatch +
  observable regex count in the validator
- B2: `groupByBindingKind` clarify strategy with `maxRounds` budget and
  fieldNames-templated copy; `cases[]` demoted to optional override
- B3: `binding.sources[]` schema with `capabilityOutput > userUtterance >
  default` priority; `capabilityOutput` NotImplemented + xfail placeholder;
  deprecated `extraction` alias with validator warning + migration guidance

**Non-Goals:**

- No capabilityOutput execution implementation
- No capability dependency edges (D2), no approval/subject-hash changes (D4)
- No Gateway changes, no new dependencies
- No frontend changes, with one sanctioned exception recorded in proposal.md: the
  offline release gate's spawn env (`scenario-runner.ts`), which was making live LLM
  calls with inherited credentials
- No new matcher kinds beyond the three named kinds in this batch

## Decisions

1. **Named kinds encode as structured matcher configs, not new regex syntax.**
   `prefixed: {prefix: [...]}`, `suffixed: {suffix: [...]}`,
   `valueShape: {shape: <name>}` compiled by the matching layer into bounded
   regexes at load time. Rationale: composable, explainable (a clarify prompt
   can be derived from prefixes/suffixes), and auditable by the validator.
   Alternative considered: keep regex but require naming — rejected, since it
   preserves unlimited expressiveness without composability.

2. **`valueShapes` live at catalog top level** (`semantic-types.yaml`
   `valueShapes: {plantCode: '^[A-Z0-9]{4}$', ...}`), referenced by matcher
   and validated against the input `pattern` contract. Rationale: one home for
   duplicated shapes; matches the spec requirement to consolidate
   `^[A-Z0-9]{4}$` (today duplicated in Inventory + PO plant inputs).

3. **Plant rewrite = named kinds + one justified regex.** The
   prefixed/suffixed form ("在 1000 工厂") maps to prefixed+suffixed+valueShape.
   The bare-code fallback with lookaround guards (`(?<!\d)([A-Z]\d{3}|\d{4})(?!\d)`)
   cannot be expressed by the named kinds and stays a regex matcher carrying a
   justification. Equivalence is proven by matcher_cases staying 23/23; the
   valueShape `^[A-Z0-9]{4}$` accepts letter-mixed codes (e.g. AB12) the old
   extraction regex rejected, which aligns extraction with the input pattern —
   no existing eval case depends on the stricter legacy behavior (verified by
   grep before the change).

4. **Regex count is a validator metric, not a gate.** The validator prints the
   total number of regex matchers in the semantic-type catalog plus
   capability-level regex matchers; justification is mandatory per matcher.
   The count is reported so decline is observable, but a nonzero count does
   not fail validation. Rationale: Plant's guarded bare-scan is a legitimate
   escape-hatch case today.

5. **Clarify strategy is declaration-driven with engine-level round tracking.**
   `clarifyPrompt.zh-CN.strategy: groupByBindingKind` + `maxRounds: 2`. The
   clarify renderer groups missing fields by source group (today: one
   userUtterance group; future: per capabilityOutput source), renders one
   prompt per group via `fieldNames` templates, and counts rounds in the turn
   state; budget exhaustion degrades to the `fallback` template. `cases[]`
   entries are checked first (exact missing-set match) and stay as overrides.
   Rationale: PR's 6 required fields currently collapse to fallback
   immediately; grouping makes one prompt carry all six with no combination
   enumeration. Alternative considered: fully generative LLM prompts —
   rejected (rule mode must stay deterministic and LLM-free).

6. **Binding is a superset shape with a deprecated alias, not a rename.**
   New shape `binding.sources[]`; the loader normalizes legacy `extraction:`
   into a single `userUtterance` source internally. The validator emits a
   warning per `extraction:` usage with migration text. Priority
   (`capabilityOutput > userUtterance > default`) is implemented in the
   resolver ordering even though the capabilityOutput branch raises
   NotImplemented — the ordering is testable and the xfail test pins the
   future landing point. Rationale: no flag day for existing declarations;
   schema freeze lands with the target shape already first-class.

## Risks / Trade-offs

- [Plant valueShape slightly loosens extraction (AB12-style codes now
  extractable)] → Mitigation: verified no eval case depends on the stricter
  behavior; extraction and input validation become consistent; matcher_cases
  must stay 23/23 as the equivalence gate.
- [Grouped clarify copy loses per-combination hand-written nuance] → Mitigation:
  `cases[]` override checked first; PR/Inventory copy regenerated from
  fieldNames templates and compared against current expected texts in tests.
- [Round tracking is a new stateful mechanism (today clarify is single-shot)]
  → Mitigation: budget state lives in the turn-level read state, serialized
  with the existing conversation contracts; tests pin 1/2/3+ missing-field
  paths and the ≤maxRounds invariant.
- [Deprecated alias keeps two shapes alive in the schema] → Mitigation: the
  alias is explicitly marked deprecated in schema descriptions; validator
  warning names the migration target; removal is a follow-up after all
  declarations migrate.

## Migration Plan

1. Schemas first: extend `semantic-type-catalog.schema.json`
   (kinds + valueShapes + justification), `capability.schema.json`
   (clarify strategy fields), `extraction-declaration.schema.json`
   (binding.sources[] + deprecated extraction).
2. Loader + matching engine: compile named kinds; normalize alias.
3. Registry data: rewrite Plant with named kinds; add valueShapes.plantCode;
   restructure PR/Inventory clarifyPrompt to strategy form.
4. Validator: justification check, regex count metric, alias warning.
5. Tests: matcher_cases equivalence gate, clarify round tests, binding
   priority tests, xfail placeholder, validator tests.

## Open Questions

(none — remaining unknowns are implementation-level and resolved during the
design phase Design Doc.)
