# Proposal: declarative-intent-hardening

## Why

The declarative intent extraction layer (registry-driven matchers, clarify
prompts, and per-input extraction declarations) is functionally correct but has
three structural weaknesses that will force expensive rework once the registry
schema is frozen: free-form regex matchers are uncomposable and unexplainable,
clarify prompts enumerate missing-field combinations (exploding with 6 required
PR fields), and extraction blocks hard-code the assumption that parameters come
only from the user utterance. These are closed now, before schema freeze, at
the lowest cost point.

## What Changes

- **B1 — Matcher kind whitelist.** Add named matcher kinds `prefixed`,
  `suffixed`, and `valueShape` (referencing a new shared `valueShapes` section
  in the semantic-type catalog) and rewrite the Plant matcher with them.
  Free-form `regex` matchers are demoted to an escape hatch: every remaining
  regex matcher must carry a `justification` field, and
  `scripts/validate-registry-contract.py` prints the current regex-matcher
  count so the number becomes an observable, reducible metric. The duplicated
  plant pattern `^[A-Z0-9]{4}$` is consolidated into
  `valueShapes.plantCode`. **BREAKING** for registry authors: un-justified
  regex matchers are rejected by the validator.
- **B2 — Clarify de-enumeration.** Add a `groupByBindingKind` clarify strategy
  with a `maxRounds` budget (2): missing fields from the same source group are
  merged into one prompt whose copy is generated from `intent.fieldNames`
  templates instead of hand-written per-combination `cases[]`. The `cases[]`
  list remains as an optional override mechanism for special copy, not the main
  path. PR (6 required fields) is covered by tests for 1 / 2 / 3+ missing
  fields, asserting round count stays within `maxRounds` and one prompt carries
  all missing fields of a group.
- **B3 — Extraction generalized to binding.** The `extraction` block is
  generalized to `binding` with a `sources[]` list of three kinds:
  `userUtterance` (today's matchers), `capabilityOutput` (future dependency
  edges — **not implemented in this batch**, a NotImplemented path with an
  xfail placeholder test), and `default`. Priority is
  `capabilityOutput > userUtterance > default`; a derivable value is never
  elicited from the user. The old `extraction:` shape is retained as a
  deprecated alias: the validator emits a warning with migration guidance.
  **BREAKING** for future registry authors only after deprecation is removed;
  the alias keeps existing declarations valid now.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `declarative-intent-extraction`: matcher kinds are whitelisted to
  prefixed/suffixed/valueShape with a justified-regex escape hatch; clarify
  prompts move from case enumeration to a group-based strategy with a round
  budget; extraction declarations generalize to binding sources with defined
  priority and a deprecated extraction alias.

## Impact

- `registry/semantic-types.yaml`, `registry/capabilities.yaml`
- `schemas/semantic-type-catalog.schema.json`, `schemas/capability.schema.json`,
  `schemas/extraction-declaration.schema.json`
- Agent extraction engine: `agent/sap_nexus_agent/extraction/` (matching,
  engine, clarify) and registry loader as needed
- `scripts/validate-registry-contract.py`
- Tests: matcher equivalence must stay green (matcher_cases 23/23), new B2
  clarify-round tests, B3 xfail placeholder and validator warning tests
- Not touched: frontend, Gateway, approval semantics, SAP execution paths
- No new dependencies

## Scope note (no-split decision)

B1/B2/B3 were considered for splitting into three changes and kept as one: the
three items share `registry/capabilities.yaml`, the registry contract schemas,
the extraction engine, and the registry validator, so splitting would create
cross-change conflicts on the same files with no delivery benefit. Each item
keeps its own task group, independent commit series, and exit criteria inside
this change.
