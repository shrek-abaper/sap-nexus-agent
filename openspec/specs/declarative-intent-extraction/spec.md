# declarative-intent-extraction Specification

## Purpose
Declarative, registry-driven intent extraction for the rule-based agent path:
capability declarations and a shared semantic-type extraction catalog replace
hand-coded per-capability keyword sets and regex extractors, so a newly
registered capability becomes usable in rule mode without agent code changes.
## Requirements
### Requirement: Declaration-driven single-turn intent extraction

The rule-based intent path SHALL detect capabilities and extract slot
parameters exclusively from registry declarations: capability-level
`primaryKeywords` for trigger detection, optional `weakKeywords` that
participate in ambiguity counting only (never trigger), and per-input
`binding` sources (matchers from the `userUtterance` kind, semantic-type
references, or keyword constants) for slot filling. The extraction engine
SHALL contain no capability-specific branches: adding a capability with valid
extraction declarations SHALL make it recognizable and slot-fillable in rule
mode without code changes. Ambiguity SHALL be flagged when two or more
capabilities weakly or primarily match while no capability has a primary
keyword hit. Technical-override rejection (RFC name / OData override
detection) SHALL take priority over declaration-driven matching, unchanged
from the legacy behavior.

#### Scenario: Declared capability recognized without code change

- **WHEN** a capability with `primaryKeywords` and input binding declarations
  is registered in the registry and a user utterance contains one of its
  primary keywords
- **THEN** the rule path surfaces that capability as a matched intent with
  parameters extracted per its declarations
- **AND** no agent source file needed modification to enable it

#### Scenario: Undeclared keyword does not trigger

- **WHEN** a capability has no binding declarations and a user utterance
  matches nothing else
- **THEN** the rule path produces no matched intent for that capability

#### Scenario: Weak keyword alone does not trigger but counts toward ambiguity

- **WHEN** an utterance contains only weak keywords of two capabilities and no
  capability's primary keyword
- **THEN** neither capability is triggered as a matched intent
- **AND** the turn is flagged as keyword-ambiguous (option-showing behavior)

#### Scenario: Technical override still rejected first

- **WHEN** an utterance contains an RFC name or OData override while also
  containing a declared primary keyword
- **THEN** the rule path rejects on technical override and produces no matched
  intents

### Requirement: Shared semantic-type extraction catalog

The system SHALL provide a semantic-type extraction catalog
(`registry/semantic-types.yaml`) defining concept-level matchers keyed by
semantic type (e.g. `Plant`, `MaterialNumber`, `Quantity`, `Date`). Input
binding declarations SHALL be able to reference a catalog entry by
`semanticType` instead of inlining a matcher, so the same concept-level
extraction knowledge is defined once and reused across capabilities.
Capability-level matchers SHALL be able to override or supplement the catalog
entry. Matchers SHALL support an ordering priority across a capability's
inputs. Cross-field exclusion SHALL be value-based: a field's extracted value
SHALL be rejected when it equals an extracted value of a field listed in its
`excludes` declaration.

Catalog matchers SHALL use named kinds `prefixed` (value following a declared
prefix token), `suffixed` (value preceding a declared suffix token), and
`valueShape` (value matching a named shape defined in the catalog-level
`valueShapes` section, e.g. `plantCode`). Free-form `regex` matchers SHALL be
an escape hatch only: every regex matcher in the semantic-type catalog MUST
carry a `justification` field explaining why the named kinds cannot express it,
and the registry validator SHALL report the total number of regex matchers in
use — catalog and capability-level counted separately — so the count is an
observable, reducible metric. A pattern duplicated across capability inputs
SHALL be defined once as a `valueShapes` entry, and the duplicated input
patterns SHALL be aligned to that shape.

#### Scenario: Two capabilities share one concept matcher

- **WHEN** two capabilities declare inputs whose binding references the same
  semantic type in the catalog
- **THEN** both extract that field using the single catalog matcher definition

#### Scenario: Exclusion prevents value reuse

- **WHEN** a document-number matcher for one input declares exclusion of fields
  already extracted (e.g. vendor and plant) and the candidate value equals one
  of those fields' extracted values
- **THEN** the document-number extraction rejects that candidate value

#### Scenario: Conditional field extraction with keyword-to-constant mapping

- **WHEN** a keyword matcher declares a constant `value` (e.g. an
  account-assignment category matched from a phrase) and another input
  declares extraction `when` that constant is present plus conditional
  requiredness (`requiredWhen`)
- **THEN** the dependent input is extracted and counted as missing only when
  the condition holds
- **AND** when the condition does not hold, the dependent input is neither
  extracted nor reported missing

#### Scenario: Regex escape hatch requires justification

- **WHEN** the registry is validated and a semantic-type catalog matcher uses
  the `regex` kind without a non-empty `justification`
- **THEN** validation fails with an error naming the matcher
- **AND** capability-level regex matchers are included in the reported count
  without being rejected, so the metric stays reducible as they migrate to
  named kinds

#### Scenario: Named shape consolidates duplicated patterns

- **WHEN** two capability inputs constrain a value with the same pattern (e.g.
  `^[A-Z0-9]{4}$` for plant)
- **THEN** the pattern is defined once in the catalog `valueShapes` section and
  the duplicated input patterns are aligned to that shape

#### Scenario: Named kinds rewrite preserves matcher behavior

- **WHEN** a catalog matcher is rewritten from regex to the named kinds
  (prefixed / suffixed / valueShape)
- **THEN** every previously passing matcher eval case still passes with the
  same extracted values

### Requirement: Behavioral parity for migrated capabilities

Migration of the existing registered capabilities to declaration-driven
extraction SHALL preserve observable behavior exactly: for any utterance, the
produced matched intents, extracted parameter values, missing-parameter lists,
clarification messages, ambiguity flags, and five-state decisions SHALL be
identical to the pre-migration hardcoded path. The agent test baseline and
call-plan eval SHALL pass unchanged during and after migration.

#### Scenario: Extraction results identical pre and post migration

- **WHEN** the same utterance set covering single-intent, multi-intent,
  ambiguous, and clarification cases is run against the legacy hardcoded path
  and the declaration-driven engine
- **THEN** every produced decision and parameter value is identical

#### Scenario: Existing baseline stays green

- **WHEN** the agent test suite and call-plan eval run after migration
- **THEN** all previously passing tests and eval cases still pass without
  modification to their expectations

### Requirement: Declaration-driven sticky continuation

Multi-turn sticky continuation SHALL resolve the inherited capability's
parameter extraction through the registry declarations and the generic
engine, with no capability-specific dispatch. New-turn detection SHALL use the
declared `primaryKeywords` of all visible capabilities. Merge semantics
(inherited parameters as base, new extraction overriding, missing recomputed
against declared required inputs) SHALL be preserved.

#### Scenario: Follow-up extraction uses declarations

- **WHEN** a follow-up utterance continues a prior turn for a capability that
  was migrated to declarations
- **THEN** parameters are re-extracted via the generic engine from that
  capability's declarations and merged with the prior turn's parameters
  exactly as the legacy path did

#### Scenario: Declared keyword of another capability starts a new turn

- **WHEN** a follow-up utterance contains a primary keyword declared by a
  different capability
- **THEN** the turn is treated as a new turn rather than sticky continuation,
  matching the legacy new-turn semantics

### Requirement: Declaration-driven CLARIFY rendering

When a matched capability is missing required inputs, the clarification text
SHALL be rendered from the capability's declared `clarifyPrompt` for the
active locale. The default rendering strategy SHALL be
`strategy: groupByBindingKind`: missing fields from the same source group
SHALL be merged into a single prompt whose copy is generated from
`intent.fieldNames` templates, with at most one prompt per group per round.
The clarify budget SHALL be `maxRounds` (default 2); when the budget is
exhausted the system SHALL degrade to the declared `fallback` template.
Hand-written exact missing-set `cases` SHALL remain supported as an optional
override checked before the strategy rendering, not as the main path. In rule
mode rendering SHALL be deterministic template rendering with no LLM call. In
llm/hybrid modes an LLM MAY rephrase the clarification, but the LLM-rendered
question SHALL only reference declared required inputs of the matched
capability and SHALL fall back to the template rendering on timeout,
malformed output, or unavailable model.

#### Scenario: Rule mode renders declared prompt deterministically

- **WHEN** a rule-mode turn matches a capability whose required input is
  missing and the declaration carries a `clarifyPrompt` for the active locale
- **THEN** the clarification message is rendered from that declaration without
  any model call

#### Scenario: LLM rephrasing stays inside the declared field set

- **WHEN** an llm/hybrid-mode turn produces a missing-parameter clarification
  and the model is available
- **THEN** the model-generated question asks only about declared required
  inputs of the matched capability
- **AND** any model failure, timeout, or out-of-scope question falls back to
  the deterministic template rendering

#### Scenario: Missing locale declaration falls back

- **WHEN** a declaration lacks a `clarifyPrompt` for the active locale
- **THEN** the system falls back to a default locale prompt derived from the
  missing input names rather than failing

#### Scenario: Grouped prompt carries all missing fields of one group

- **WHEN** a capability with multiple required fields is missing several
  fields from the same source group (e.g. all six PR required inputs)
- **THEN** one clarification prompt lists all of them
- **AND** the number of clarify rounds does not exceed `maxRounds`

#### Scenario: Budget exhaustion degrades to fallback

- **WHEN** clarification rounds reach `maxRounds` and required fields are
  still missing
- **THEN** the system renders the declared `fallback` template instead of
  starting another clarify round

#### Scenario: Explicit cases still override strategy rendering

- **WHEN** the declaration carries a hand-written `cases` entry whose missing
  set matches the current missing fields exactly
- **THEN** that entry's text is rendered, taking precedence over
  `groupByBindingKind` copy generation

### Requirement: Input binding sources and priority

Per-input declarations SHALL support a `binding` block with a `sources[]`
list of three kinds: `userUtterance` (matcher-driven extraction from the user
utterance, equivalent to today's extraction matchers), `capabilityOutput` (a
value derived from another capability's fact, reserved for future dependency
edges), and `default` (a constant fallback value). Source priority SHALL be
`capabilityOutput > userUtterance > default`: when a capabilityOutput source
can produce a value the system MUST NOT elicit the field from the user and
MUST NOT fall back to a default. The `capabilityOutput` kind SHALL be
accepted and validated by the schema and validator, but its execution path
MAY remain unimplemented in this batch; an unimplemented path SHALL be
surfaced by a failing xfail placeholder test so future implementation has a
fixed landing point.

#### Scenario: capabilityOutput beats user utterance

- **WHEN** an input declares both a `capabilityOutput` source and a
  `userUtterance` matcher and the capabilityOutput source can produce a value
- **THEN** the resolved value comes from the capabilityOutput source
- **AND** no clarification question for that field is raised

#### Scenario: default only fills when no other source produces

- **WHEN** an input declares a `default` source and no higher-priority source
  produces a value
- **THEN** the default value fills the input

#### Scenario: unimplemented capabilityOutput has a failing placeholder

- **WHEN** the capabilityOutput execution path is not yet implemented
- **THEN** an xfail-marked test referencing that path fails with a clear
  not-implemented reason instead of being silently absent

### Requirement: Deprecated extraction alias with migration warning

The pre-existing `extraction:` declaration shape SHALL remain valid as a
deprecated alias of `binding:` with a single `userUtterance` source. The
registry validator SHALL emit a warning for every `extraction:` usage and the
warning SHALL carry migration guidance pointing at the `binding.sources[]`
shape. Declarations that use neither `binding` nor `extraction` for an input
that requires extraction SHALL be reported as invalid exactly as before.

#### Scenario: extraction alias still works with a warning

- **WHEN** the registry is validated and an input declares `extraction:`
  matchers
- **THEN** validation succeeds
- **AND** a warning naming the deprecated shape and its `binding.sources[]`
  replacement is reported

#### Scenario: binding shape validates without warnings

- **WHEN** the registry is validated and an input declares `binding.sources[]`
- **THEN** validation succeeds with no deprecation warning

