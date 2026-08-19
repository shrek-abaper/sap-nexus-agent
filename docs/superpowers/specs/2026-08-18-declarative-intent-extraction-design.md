---
comet_change: declarative-intent-extraction
role: technical-design
canonical_spec: openspec
archived-with: 2026-08-19-declarative-intent-extraction
status: final
---

# Design Doc: declarative-intent-extraction

Deep technical refinement of the open-phase framework
(`openspec/changes/declarative-intent-extraction/design.md`, decisions D1-D7).
This document adds the implementation-level design confirmed during
brainstorming on 2026-08-18: final declaration schema, engine algorithm,
catalog entries, parity harness mechanics, CLARIFY pipeline, and the spec
patches written back to the delta specs. It does not restate the proposal.

## 1. Declaration Schema (final shape)

### 1.1 Capability-level `intent` block

```yaml
intent:
  primaryKeywords: [ "库存", "可用量", "可用库存", "还有多少" ]  # regex semantics
  weakKeywords: [ "有没有" ]        # ambiguity counting only, never triggers
```

- `primaryKeywords`: each entry is a regex pattern applied with `re.search`;
  plain strings behave as substring matches. A hit triggers the capability
  (single/multi-intent) and counts as a primary hit for ambiguity detection.
  PO's boundary-aware pattern `(?<![A-Za-z])PO(?![A-Za-z])` is expressible
  directly.
- `weakKeywords`: same matching mechanics, never triggers a capability;
  contributes to the weak-match count only. Ambiguity condition
  (reproducing `intent.py` `_detect_keyword_ambiguity`):
  `matched_capabilities >= 2 AND primary_hits == 0` -> `is_ambiguous=true`.
- Sticky new-turn detection consumes the union of all visible capabilities'
  `primaryKeywords` (replaces `_PRIMARY_KEYWORD_SETS`).

### 1.2 Per-input `extraction` (inline on the existing input entry)

```yaml
inputs:
  - name: material
    required: true
    extraction:
      matchers:                       # ordered; first producing a value wins
        - kind: semanticType          # delegate to catalog entry
          ref: MaterialNumber
        - kind: regex                 # inline pattern, capture group 1 = value
          pattern: "([A-Za-z0-9][A-Za-z0-9\\-/]+)"
      priority: 10                    # extraction order across inputs (desc)
      excludes: [ plant, unit ]       # VALUE-based exclusion
      resolver: text                  # date | quantity | text
      when:                           # optional condition
        field: acct_assgn_cat
        equals: "K"
    clarifyPrompt:
      zh-CN:
        cases:                        # exact missing-set match, checked first
          - missing: [ material ]
            text: "请提供要查询的物料编号。"
        fallback:                     # join template for any other missing set
          template: "请提供要查询的物料编号和工厂。"
```

### 1.3 Keyword-to-constant and conditional requiredness (PR case)

`MM.PR.CreateDraft`'s account-assignment dependency is expressed without new
matcher kinds:

```yaml
inputs:
  - name: acct_assgn_cat
    extraction:
      matchers:
        - kind: keyword
          pattern: "间采|账号分配\\s*[Kk]"
          value: "K"            # matched -> constant value (no capture)
  - name: cost_center
    extraction:
      matchers:
        - kind: regex
          pattern: "成本中心\\s*(\\d+)"
      when: { field: acct_assgn_cat, equals: "K" }
    requiredWhen: { field: acct_assgn_cat, equals: "K" }
```

`when` gates extraction; `requiredWhen` adds the field to `missing` only when
the condition holds. Both use the same `{field, equals}` condition shape.
`required` (unconditional) remains on the input entry as today.

### 1.4 `clarifyPrompt` rendering model

Locale-keyed. `cases` is an ordered list of exact missing-set matches (set
equality, order-insensitive on input names); `fallback.template` supports a
`{fields}` placeholder expanded with per-field display names from a
capability-level `fieldNames` locale map (PR's "请提供: 物料编号, 工厂, ..."
join is `fallback.template: "请提供: {fields}"`). `cases` checked first;
this reproduces inventory's three exact strings and PR's join format
byte-for-byte. Missing locale entry -> default-locale prompt derived from
missing input names (never fails).

## 2. Extraction Engine

Single module, zero capability branches:

1. **Trigger scan**: for each visible capability with an `intent` block, test
   `primaryKeywords` (trigger + primary hit) and `weakKeywords` (weak hit).
   Technical-override rejection (existing RFC-name / OData-override guards)
   runs before and short-circuits everything, unchanged.
2. **Slot extraction**: per triggered capability, iterate inputs carrying
   `extraction` in `priority` order (desc, stable by declaration order). For
   each input: evaluate `when` (skip if unmet), run matchers in order; first
   value wins. Value-based exclusion: an input's extracted value must not
   equal any extracted value of inputs listed in `excludes` (uppercase-
   normalized comparison where the current extractors do so).
3. **Resolvers**: `text` (verbatim, optional uppercase normalization per
   declaration filter), `date` (ISO capture verbatim), `quantity` (numeric
   capture + paired unit co-extraction, e.g. `10EA` -> quantity `10`, unit
   `EA`). Resolver behavior is lifted verbatim from current extractors.
4. **Missing computation**: `required` inputs without values + `requiredWhen`
   inputs whose condition holds without values, in declaration order.
5. **Output**: unchanged `MatchedIntent` / `IntentParseResult` shapes -
   single triggered capability -> single-intent result; >1 -> multi-intent
   result with per-capability matched intents (selector decides
   ESCALATE_TO_PLANNER); ambiguity flag from step 1.

Sticky continuation calls the same engine for parameter re-extraction of the
inherited capability; merge semantics (inherited as base, new overrides,
missing recomputed) unchanged. The inventory material-CLARIFY quirk
(lowercase-material suspicion re-ask) is preserved during parity via a
declaration-scoped guard flag on the material input
(`reaskSuspect: true`) - engine-level generic behavior, removal deferred to a
follow-up change.

## 3. semantic-types.yaml Catalog Entries

All entries lifted verbatim from current extractors; structure: semantic type
id, ordered matcher list (same kinds), value filters
(`minLength`, `notIn`, `prefixBlacklist`, `toUpperCase`), priority hint.

| Entry | Replaces | Notes |
|-------|----------|-------|
| `Plant` | `_extract_plant` / PR plant | primary 工厂-prefixed pattern + bare-code fallback with lookaround guards; PO narrows via capability-level override (drops fallback) |
| `MaterialNumber` | `_extract_material` / PR material / `_extract_po_material` | token scan; filters: `minLength: 5` (len>4), `notIn: [RFCNAME]`, `prefixBlacklist: [BAPI_]`, uppercase compare; PR/PO use prefixed patterns via override |
| `Quantity` / `Unit` | `QUANTITY_PATTERN` / `UNIT_PATTERN` | co-capture; unit uppercased |
| `Date` | `DATE_PATTERN` | ISO date capture |
| `PurchasingGroup` | `PURCHASING_GROUP_PATTERN` | 采购组-prefixed, uppercased |
| `Vendor` | `PO_VENDOR_PATTERN` | PO-specific, referenced directly |
| `PONumber` | `PO_NUMBER_PATTERN` | value-excluded against vendor/plant via `excludes` |

## 4. Parity Harness

- Per capability, a **frozen fixture table**: `utterance -> expected
  (decision_type, capability_id, parameters, missing, clarification,
  is_ambiguous)` derived from existing tests plus an adversarial set
  (single/multi-intent, ambiguity, partial params, technical override,
  sticky follow-ups including overlay merge and new-turn switch).
- Migration period: differential mode - legacy path and engine both run on
  the fixture table, asserting byte-identical results (clarification text
  included).
- Post-migration (legacy deleted): the same tables assert against the frozen
  expectations directly and remain permanent regression tests.
- Each migration step (PR -> Inventory -> PO) is a standalone commit; full
  agent suite + call-plan eval green at every step.

## 5. CLARIFY Pipeline

- **Rule mode**: deterministic rendering (1.4). No model calls anywhere on
  the path.
- **llm/hybrid**: after template rendering, an optional rephrase step sends
  the rendered question plus the declared missing-field closed set; the model
  must return a question referencing only declared missing inputs. Output
  validation rejects supersets/unknown fields, timeouts, malformed output;
  any rejection falls back to the template text. Model unavailable ->
  template (identical to rule mode), preserving the hybrid fallback
  contract.

## 6. Validation (registry contract + JSON Schema)

Mirrors S1 schema: matcher kinds, `when`/`requiredWhen` field/equals shape,
`excludes` input-name resolution, regex compile + backtracking guard
(length + nested-quantifier heuristic, bounded sample-input timeout),
`semanticType.ref` resolution against the catalog, `clarifyPrompt` locale
completeness (every required/requiredWhen input covered in every supported
locale, `cases`/`fallback` structure), duplicate catalog id rejection,
capability + catalog loaded atomically under one snapshot id. Gateway
indifference covered by a gateway-side test loading a registry with
extraction metadata.

## 7. Spec Patches (written back to delta specs)

1. `declarative-intent-extraction`:
   - trigger requirement gains `weakKeywords` (ambiguity counting, no
     trigger) and the explicit ambiguity condition;
   - new scenario: conditional extraction (`when`/`value`/`requiredWhen`);
   - exclusion semantics corrected to value-based;
   - clarifyPrompt rendering: `cases`/`fallback` structure and scenarios.
2. `registry-ontology-contract`: validator requirement extends to
   `weakKeywords`, `when`/`requiredWhen`, and keyword-`value` structure
   validation.

## 8. Testing Strategy

- Engine unit tests (trigger, priority, exclusion, conditional, resolvers,
  ambiguity, technical override precedence)
- Parity fixture tables (per capability, differential then frozen)
- Validator tests (compile failure, backtracking guard, dangling ref, locale
  incompleteness, duplicate id, malformed when/value)
- Gateway indifference test
- Fixture capability (declarations only, no code) end-to-end rule-mode test:
  recognize, slot-fill, CLARIFY
- Full agent suite + call-plan eval green at every migration step

---

## Verification Record

Task 20 performed a full closeout verification sweep on 2026-08-19 (HEAD `1271d57`, verification recorded in `openspec/changes/declarative-intent-extraction/verification.md`). All completion criteria passed:
- Registry contract validation: `EXIT CODE: 0`, contract valid
- Full agent test suite: `15 failed, 1273 passed, 1 skipped` — **exact match to documented pre-existing baseline** (9 test_eval_runner, 1 test_intent, 1 test_llm_intent, 4 test_orchestrator). These 15 failures are confirmed pre-existing PO vendor/PONumber alphanumeric-matching gaps and a stale canonical-JSON hash test vector — both explicitly ruled out of scope during Task 18. They existed identically at the plan's own pre-Task-1 base commit `20f96d8` (verified empirically via disposable git worktree). This is NOT a regression introduced by declarative-intent-extraction.
- Call-plan eval results: inventory `7/7`, PR `9/9`, dry-run `3/3` (+1 documented pending/skip)
- OpenSpec validate: `21/21 passed`, `0 failed`
- Gateway tests: `BUILD SUCCESSFUL`, `exit 0`
- Frontend untouched: empty diff from base commit through current HEAD
- Parity-table fixture row counts (frozen baseline):
  - Inventory: 13 rows
  - PO: 11 rows
  - PR: 12 rows
  - Total: 36 rows

### Sanctioned Design Reconciliations (Marked Applied)

1. **`triggerKeywords` added to the intent block** (Task 5, 10)
   Legacy trigger sets differ from primary/weak ambiguity tables per capability (e.g. inventory triggers on `有没有` which is a weak keyword, PR primary list has `创建采购` while trigger list lacks it). `triggerKeywords` defaults to `primaryKeywords` when absent; ambiguity counting and sticky new-turn detection use `primaryKeywords`/`weakKeywords` only.

2. **`clarifyPrompt` lives at capability level** (Task 5, 10)
   `clarifyPrompt` is capability-level (`intent.clarifyPrompt.<locale>`) not inside a single input, to support exact missing-set matches spanning inputs and PO's virtual `filter` missing name expression.

3. **`requireAny` group requiredness** (Task 5)
   PO synthesizes `missing_parameters=["filter"]` when no filter was extracted. Expressed as `intent.requireAny: {inputs: [...], missingName: filter}` - engine-generic any-of requiredness, not a PO branch.

4. **`toUpperCase` split into `toUpperCaseCompare` / `toUpperCaseOutput`** (Task 2, 3)
   Inventory material compares uppercased but returns original token; PR unit and purchasing group return uppercased values. Separated into `toUpperCaseCompare` (for value comparison, including `excludes`) and `toUpperCaseOutput` (for returned values).

5. **Sticky non-inventory clarification text changes** (sanctioned micro-deviation) (Task 11, 16)
   Legacy sticky CLARIFY for PR uses generic `请提供以下参数：{names}。` declaration renders `请提供: 物料编号, ...`. Parity harness marks these rows `clarification_strict: false` during differential mode; other sticky texts coincide exactly.

6. **`test_loads_exactly_four_snapshot_sources` updated to five sources** (Task 2.1)
   Test updated to expect five sources instead of four because Task 2.1's requirement is that the snapshot id must cover `registry/semantic-types.yaml`.

All reconciliations confirmed applied in implementation and verified via parity harness and test suite.
