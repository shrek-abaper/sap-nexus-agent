# Narrative Generalization Specification

## Purpose

Define the complete target behavior of a generalized, factShape-clustered, metadata-driven
narration framework. Adding a capability's narration requires only a `narrative` declaration in
`capabilities.yaml` (factShape + template ids + fieldMapping + detailFormatter), not new Python
entry points, prompt builders, or template fallbacks. The three existing capabilities
(inventory single-value, purchase-order list, PR action-receipt) all flow through one unified
dispatch.

## Domain model

- `narrative` declaration (per capability, in `capabilities.yaml`):
  - `factShape`: `single-value` | `list` | `action-receipt` - clusters by fact data shape.
  - `promptTemplate`: id referencing a centralized prompt template in `narrator.py`.
  - `fallbackTemplate`: id referencing a deterministic LLM-unavailable template.
  - `fieldMapping`: fact fields (fixed + evidence dynamic) -> template variables.
  - `detailFormatter`: `mrp-table` | `po-list` | `none` - pluggable detail renderer id.
- `NarrativeConfig` (runtime): the loaded `narrative` declaration for a capability.
- Template registry (in `narrator.py`): centralized prompt/fallback template strings keyed by id.
- Detail formatter registry (in `narrator.py`): pluggable formatters keyed by id
  (`mrp-table`, `po-list`, `none`); unknown id falls back to `none`.
- `NarrativeOutcome`: the narration text produced by the framework.
- `build_pr_create_fact` (new): fact builder for PR action-receipt; mirrors
  `build_availability_fact` / `build_purchase_order_facts`.

## Requirements

### Requirement: capability schema supports a narrative declaration

`schemas/capability.schema.json` SHALL accept an optional `narrative` object on each capability
with `factShape`, `promptTemplate`, `fallbackTemplate`, `fieldMapping`, and `detailFormatter`.
Capabilities without a `narrative` declaration SHALL fall back to generic fact-based narration.

#### Scenario: Schema validates a capability with a narrative block

- **WHEN** a capability declares a `narrative` block with all required fields
- **THEN** `openspec validate --all --strict` passes
- **AND** the registry loader exposes the `narrative` config on the capability descriptor

#### Scenario: Capability without narrative falls back to generic

- **WHEN** a capability has no `narrative` block
- **THEN** narration uses `_GENERIC_GUIDANCE` and a generic fact-based template
- **AND** no error is raised

### Requirement: factShape clusters narration pipelines by fact data shape

The framework SHALL provide three narration entry points keyed by `factShape`:
`narrate_single_value`, `narrate_list`, `narrate_action_receipt`. Each entry point SHALL use
`fieldMapping` to fill template variables and `detailFormatter` to render detail. No
per-capability entry point (e.g. `narrate_fact`, `narrate_purchase_order_facts`) SHALL remain as
hardcoded field logic.

#### Scenario: single-value narration (inventory)

- **WHEN** a fact with `factShape: single-value` and `detailFormatter: mrp-table` is narrated
- **THEN** the output has the structured title + available quantity + MRP detail table
- **AND** the LLM path appends the deterministic detail table after the LLM summary

#### Scenario: list narration (purchase order)

- **WHEN** facts with `factShape: list` and `detailFormatter: po-list` are narrated
- **THEN** the output lists key order fields and truncates beyond the limit
- **AND** empty list returns "无匹配记录。"

#### Scenario: action-receipt narration (PR create)

- **WHEN** a fact with `factShape: action-receipt` is narrated
- **THEN** the output states the created PR number
- **AND** missing PR number yields a "未返回 PR 号" message

### Requirement: detailFormatter is pluggable

A detail formatter registry SHALL map `mrp-table`, `po-list`, `none` to formatter functions.
An unknown formatter id SHALL fall back to `none` (no detail rendered). New formatters require
registering a function but no new narration pipeline.

#### Scenario: Unknown detail formatter falls back to none

- **WHEN** a narrative declaration specifies `detailFormatter: unknown-xyz`
- **THEN** narration proceeds with no detail rendered
- **AND** no error is raised

### Requirement: Orchestrator dispatches by factShape

The orchestrator SHALL have a unified `_finalize_narrative` that dispatches by
`narrative.factShape` from the capability descriptor. No `if capability_id == INVENTORY` branching
for narration SHALL remain. PR create SHALL flow through this dispatch (action-receipt), not an
orchestrator f-string.

#### Scenario: PR create uses the framework

- **WHEN** a PR create execution succeeds
- **THEN** `build_pr_create_fact` builds the fact
- **AND** `narrate_action_receipt` produces the response text via the framework
- **AND** no f-string narration remains in `_finalize_pr_create`

### Requirement: PR create has a fact builder

`build_pr_create_fact` SHALL build a `ReasoningFact` (predicate `purchaseRequisitionCreated`,
deterministic, confidence 1.0) from a successful PR create execution result, carrying the PR
number in evidence. The fact stays deterministic; no LLM text in evidence.

#### Scenario: Successful PR create builds a fact

- **WHEN** a PR create execution returns a PR number
- **THEN** the built fact has `predicate: purchaseRequisitionCreated` and the PR number in evidence
- **AND** `deterministic: true`, `confidence: 1.0`

### Requirement: Adding a capability's narration requires zero narrator/orchestrator code

A test SHALL register a synthetic capability with only a `narrative` declaration (no new Python
narrator/orchestrator code) and narrate it through the framework successfully.

#### Scenario: Synthetic capability narrates via declaration only

- **WHEN** a synthetic capability with a `narrative` declaration (factShape single-value,
  fieldMapping, detailFormatter none) is narrated
- **THEN** the framework produces a grounded narrative using only the declaration
- **AND** no new entry point or template function was added for it

### Requirement: Existing inventory and PO narration is behavior-preserving

Inventory (single-value + mrp-table, structured MD04 table output) and PO (list + po-list)
narration output SHALL not regress. `evals/inventory_availability_cases.yaml` SHALL pass 7/7.
Agent tests SHALL be green.

#### Scenario: Inventory structured output preserved

- **WHEN** an inventory fact with mrpElementLines is narrated via the framework
- **THEN** the output contains the title, available quantity, and MRP detail table
- **AND** matches the pre-generalization format

## Constraints and invariants

- Fact-chain determinism: `deterministic: const true`, `confidence: const 1.0`; LLM narrative
  never in `evidence`/`primaryFact`; `_SYSTEM_CONSTRAINT` unchanged.
- Behavior preservation: existing inventory/PO narrative output formats must not regress.
- Identifier stability: no rename of capabilityId/businessObject/factType/bindingId.
- READ/WRITE boundary and approval gating unchanged.
- `narrative` is optional; capabilities without it fall back to generic narration.

## Non-goals

- No change to fact-chain determinism, intent recognition, LLM auth, OData service, SAP execution.
- No rename of existing identifiers.
- No new capability; only refactor narration for the 3 existing ones.
- No auto-generation of narrative declarations for future capabilities.
