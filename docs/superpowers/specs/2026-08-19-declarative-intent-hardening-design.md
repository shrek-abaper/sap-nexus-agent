---
comet_change: declarative-intent-hardening
role: technical-design
canonical_spec: openspec
archived-with: 2026-08-20-declarative-intent-hardening
status: final
---

# Declarative Intent Hardening — Technical Design

## 1. Context

Registry contract freeze is imminent. Three structural weaknesses of the
declarative intent layer must be closed first (see proposal.md for
motivation): free-form regex matchers (B1), clarify prompt combination
enumeration (B2), and extraction's single-source assumption (B3). This
document refines the open-phase design.md into implementable detail:
compilation algorithms, state placement, resolver ordering, and boundary
conditions.

Current code shapes:

- `registry/semantic-types.yaml` (v1) — matchers: keyword | regex |
  semanticType; `registry/capabilities.yaml` (v2) — per-input `extraction`
  blocks with matchers/resolver/priority/excludes/when/requiredWhen.
- `agent/sap_nexus_agent/extraction/_matching.py` — `match_value` per matcher;
  engine.py iterates matchers first-hit-wins and resolves via
  resolver text/quantity/date; clarify.py renders single-shot prompts.
- `schemas/semantic-type-catalog.schema.json`,
  `schemas/extraction-declaration.schema.json`,
  `schemas/capability.schema.json`; `scripts/validate-registry-contract.py`
  validates registry against these.

## 2. Goals / Non-Goals

Goals: B1 whitelist with named kinds + justified regex escape hatch +
observable regex count; B2 grouped clarify with a durable round budget; B3
binding sources with defined priority, NotImplemented capabilityOutput pinned
by xfail, deprecated extraction alias with warning.

Non-goals: capabilityOutput execution, dependency edges (D2), approval
semantics (D4), Gateway changes, new dependencies. Frontend changes are a
non-goal with one sanctioned exception recorded in proposal.md (the offline
release gate's spawn env, which was making live LLM calls with inherited
credentials).

## 3. Decisions

### 3.1 Named-kind compilation (B1)

Matcher kinds compile to bounded regexes at load time:

- `prefixed: {prefix: ['在']}` → `(?:在)\s*(<shape>)(?![A-Za-z0-9])` — value
  captured after the prefix token(s); prefixes are literal tokens, alternated
  when multiple.
- `suffixed: {suffix: ['工厂']}` → `(?<![A-Za-z0-9])(<shape>)\s*(?:工厂)` — value
  captured before the suffix token(s).
- `valueShape: {shape: plantCode}` — standalone bare scan:
  `(?<![A-Za-z0-9])(<shape compiled>)(?![A-Za-z0-9])`.

Every kind carries an alphanumeric lookaround guard on each side of the captured
value that is not anchored by an affix token. **Corrected 2026-08-20:** this
document previously specified that the value component of `prefixed`/`suffixed`
needed no boundary guards because "guards come from the prefix/suffix anchors".
That is false — the affix anchors only one side, so the free side carved a
4-character window out of the middle of any longer adjacent alphanumeric token
(`DEMOA2 工厂` → `MOA2`). Because the carved value still satisfies the input's
declared `pattern`, a wrong plant reached SAP with `missing=[]` and no
clarification. See the verification report's Correctness section for the measured
table; regression pins are
`test_named_kinds_do_not_carve_shape_window_out_of_longer_adjacent_token` and
`test_inventory_plant_ignores_material_tail_adjacent_to_suffix_token`.

`valueShapes` is a catalog-level section: `{plantCode: '^[A-Z0-9]{4}$', ...}`.
The matcher compilation layer (`_matching.py`) gains a `_compile_named_kind`
path producing the same compiled-regex behavior as today's `_compile_matcher`;
`match_value` stays the single execution entry so engine code is untouched by
B1.

Plant rewrite (registry/semantic-types.yaml):

```yaml
- id: Plant
  matchers:
    - kind: prefixed
      prefix: ['在']
      valueShape: plantCode
    - kind: suffixed
      suffix: ['工厂']
      valueShape: plantCode
    - kind: regex
      pattern: '(?<!\d)([A-Z]\d{3}|\d{4})(?!\d)'
      justification: >-
        Bare 4-char code scan with digit-only lookaround guards; the
        named-kind bare scan uses alnum guards and would change behavior
        for digit-adjacent tokens.
```

Equivalence boundary: the old single regex accepted "在 X" or "X 工厂"
(prefix-only OR suffix-only); two separate named matchers preserve exactly
that alternation. The bare fallback stays regex per the confirmed design
(escape hatch has a real case; exact equivalence wins).

### 3.2 valueShapes semantics and the AB12 boundary

`plantCode: '^[A-Z0-9]{4}$'` accepts letter-mixed codes (AB12) the legacy
extraction regex `[A-Z]\d{3}|\d{4}` rejected. All existing eval/test
utterances use digit plant codes, so matcher_cases 23/23 and the full suite
hold; extraction and the input `pattern` contract become consistent. This
deliberate loosening is documented in the registry comment and covered by a
new unit test asserting the AB12 case extracts (contract, not accident).

### 3.3 Regex escape hatch and validator metric (B1)

- `semantic-type-catalog.schema.json`: matcher kinds enum gains prefixed /
  suffixed / valueShape; a regex matcher requires non-empty `justification`.
- `scripts/validate-registry-contract.py`: (a) error when a **semantic-type
  catalog** regex matcher lacks justification — capability-level regex matchers
  are counted but not rejected, so migrating them to named kinds is a reduction
  path rather than a hard gate; (b) print "regex matchers in use: N (semantic-type
  catalog M + capability-level K)" as an observable metric — a count, never a
  gate.

### 3.4 PR.CreateDraft.plant pattern (B1 item 5)

Add `pattern: '^[A-Z0-9]{4}$'` to `MM.PR.CreateDraft.plant`. Pre-change gate:
grep all eval cases (evals/*.json|yaml) and agent tests for PR utterances
with plant values that would violate the shape (e.g. lower-case or >4 char).
No case is expected to depend on the loose behavior; if one is found, the
case expectation is updated only with an explicit semantic justification.

### 3.5 Clarify strategy and round budget (B2)

Schema: `clarifyPrompt.<locale>.strategy: groupByBindingKind`,
`clarifyPrompt.<locale>.maxRounds: 2` (default). `cases[]` becomes an
optional exact-missing-set override checked before strategy rendering.

Rendering (`extraction/clarify.py`):

1. exact `cases` match → its text (unchanged behavior);
2. else strategy path: group `missing` fields by binding source group (today:
   one `userUtterance` group; future: one group per capabilityOutput source);
   per group render one prompt listing `fieldNames` display names of the
   whole group (template: "请提供: {fields}", fields joined by group);
3. budget check first: if the capability's clarify rounds have reached
   `maxRounds`, render the `fallback` template instead of a strategy prompt.

Round state: `ConversationReadState` gains
`clarify_rounds: Mapping[capabilityId, int]`, persisted and replayed with the
existing durable read state (schema_version-compatible migration: absent ⇒
empty). The engine increments the counter when it renders a strategy prompt
for a capability and resets it when the turn selects a different capability.
Fallback rendering does not increment (budget already exhausted).

PR declaration: replace the empty-cases clarifyPrompt with
`strategy: groupByBindingKind` + `maxRounds: 2` (no hand-written cases; all
six required fields share the identifier/userUtterance group). Inventory
keeps its two `cases` entries as the override mechanism.

### 3.6 Binding model and alias normalization (B3)

New loader model `BindingConfig(sources: tuple[BindingSource, ...],
elicit_if_missing: bool = True)`; `BindingSource(kind, matchers?,
fact_type?, field?, value?)` for userUtterance / capabilityOutput / default.
The loader normalizes a legacy `extraction:` block into a single
`userUtterance` source carrying the existing matchers/priority/resolver/
excludes/when/requiredWhen semantics (priority and excludes remain
input-level extraction concerns, not per-source). `ExtractionConfig` stays as
the deprecated intermediate; the engine consumes `BindingConfig` only.

Schema `extraction-declaration.schema.json`: `binding.sources[]` shape with
kind-specific subschemas; `extraction` retained with a `deprecated: true`
description. Validator emits a warning per `extraction:` usage including the
migration text ("replace extraction.matchers with
binding.sources[{kind: userUtterance, matchers: [...]}]").

Resolution order in the engine: for each input, evaluate sources in priority
order — capabilityOutput (NotImplemented raise), userUtterance (existing
matcher loop), default (constant) — first produced value wins; a field with
a produced value is never missing; a `default` source therefore suppresses
clarify for that field. `elicitIfMissing: false` skips clarification for the
field even when no source produced (used by future derived fields; no current
declaration sets it).

The xfail placeholder: `test_binding_capability_output_not_implemented`
asserts that resolving a capabilityOutput source raises NotImplementedError
with a message naming the future landing point (dependency-edge binding);
marked `@pytest.mark.xfail(strict=True, reason="capabilityOutput execution
is out of scope for declarative-intent-hardening")`.

### 3.7 Testing matrix

| Area | Test | Assertion |
|---|---|---|
| B1 equivalence | matcher_cases (unchanged file) | 23/23 |
| B1 parity pins | test_extraction_declarations.py updated | new kind structures pinned |
| B1 AB12 contract | new unit test | prefixed+suffixed extract AB12 per plantCode shape |
| B1 validator | new contract test | un-justified regex fails; count line printed |
| B2 PR missing 1/2/3+ | new tests | rounds ≤ 2; one prompt carries all group fields |
| B2 budget branch | synthetic two-group fixture | round 2 renders, round 3 degrades to fallback |
| B2 override | inventory cases tests | cases[] exact match still wins |
| B3 priority | unit tests with fake sources | capabilityOutput > userUtterance > default |
| B3 alias | validator test | warning emitted with migration text |
| B3 xfail | placeholder test | xfail strict, not-implemented message |

## 4. Risks / Trade-offs

- [Named-kind compilation subtly diverges for future catalogs (no anchors)]
  → Mitigation: unit tests pin compiled regexes for each kind.
- [Round state schema migration] → Mitigation: absent ⇒ empty dict; replay
  tests confirm old payloads round-trip.
- [Deprecated alias keeps two schema shapes] → Mitigation: `deprecated: true`
  description + validator warning; alias removal is a follow-up after all
  declarations migrate.
- [AB12 loosening] → Mitigation: documented contract change; grep-first gate
  before touching PR.plant pattern; matcher_cases as equivalence gate.

## 5. Migration Plan

Order: schemas → loader/models → matching compilation → registry data (Plant
rewrite, PR clarify, PR.plant pattern) → validator → engine resolver/clarify
round → tests. Each B-item commits separately with test names and root causes
in messages. Rollback: each item is independently revertible; the alias keeps
old declarations valid throughout.

## 6. Open Questions

None.
