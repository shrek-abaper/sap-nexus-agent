# registry-ontology-contract Specification

## Purpose
Define the release-gate contract for SAP Nexus Capability Registry semantics, executor binding readiness, governance consistency, OWL skeleton identity, eval linkage, and controlled multi-executor binding shapes without introducing runtime Gateway pilots or Knowledge Graph dependencies.
## Requirements
### Requirement: Registry schema validates semantic capability contract
The system SHALL validate `registry/capabilities.yaml` version `2` against a deterministic Registry contract that covers capability identity, semantic metadata, typed inputs, Fact-producing outputs, governance, and executor binding references. Every input MUST declare `bindingKind=identifier|fact`. `bindingKind` SHALL describe what the parameter is, and `satisfiableByFactType` SHALL describe where it may additionally come from: a fact-bound input MUST reference one published `satisfiableByFactType`, and an identifier input MAY also reference one published `satisfiableByFactType` to declare that an upstream Fact can supply it. Every output with `evidenceRole=primaryFact` MUST reference one published `factTypeRef`.

#### Scenario: All active capabilities pass Registry v2 contract
- **WHEN** the contract validator checks the active `MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`, `MM.PR.CreateDraft`, and `MM.Material.GetInfo` entries
- **THEN** validation succeeds for their stable identity, semantic IO, governance, eval linkage, and executor binding references
- **AND** each input is classified as either `bindingKind=identifier` or `bindingKind=fact`, and any input carrying `satisfiableByFactType` references exactly one published Fact Type
- **AND** their primary outputs reference `sapnexus:InventoryAvailabilityFact`, `sapnexus:PurchaseOrderSupplyFact`, `sapnexus:PurchaseRequisitionCreatedFact`, and `sapnexus:MaterialInfoFact` respectively
- **AND** the capabilities remain available to existing Agent and Gateway flows by the same `capabilityId`

#### Scenario: Fact-bound input lacks Fact Type reference
- **WHEN** an input declares `bindingKind=fact` without `satisfiableByFactType`
- **THEN** contract validation fails before graph compilation or runtime execution

#### Scenario: Identifier input declares Fact Type reference
- **WHEN** an input declares `bindingKind=identifier` together with one published `satisfiableByFactType`
- **THEN** contract validation succeeds, and the input is treated as user-suppliable with an upstream Fact as an alternative source
- **AND** a user-supplied value for that input still binds as an identifier rather than as a Fact

#### Scenario: Identifier input references an unpublished Fact Type
- **WHEN** an input declares `bindingKind=identifier` together with a `satisfiableByFactType` that no published Fact Type matches
- **THEN** contract validation fails and names the offending capability and input

#### Scenario: Primary Fact output lacks Fact Type reference
- **WHEN** a primary Fact output omits `factTypeRef` or references an unpublished Fact Type
- **THEN** contract validation fails before the capability can enter the semantic graph

#### Scenario: Malformed capability is rejected before runtime execution
- **WHEN** a Registry entry is missing required identity, semantic fields, governance fields, v2 input/output metadata, eval linkage, or executor binding reference
- **THEN** contract validation fails with a deterministic error
- **AND** the invalid entry is not treated as an executable SAP or external-system capability

### Requirement: Semantic capability and technical binding are separated
The system SHALL distinguish business semantic capability metadata from technical executor binding metadata. Agent, Workbench, LLM, and eval flows MUST use registered `capabilityId`; technical execution details MUST come from an allowlisted binding owned by Registry / binding catalog artifacts, not from external requests.

#### Scenario: Capability references allowlisted technical binding
- **WHEN** `MM.Inventory.GetAvailability` declares its technical execution mapping
- **THEN** the semantic capability identifies the business capability and evidence contract
- **AND** the technical binding identifies an allowlisted `bindingId` and executor type for the current `JCO_RFC` implementation
- **AND** callers cannot override `bindingId`, `rfcName`, OData service, CDS object, ADT path, REST endpoint, HTTP method, headers, credential reference, or JSON mapping

#### Scenario: Request-provided technical details are rejected
- **WHEN** a caller, Agent output, LLM output, eval case, or Workbench request attempts to provide raw technical execution details such as `rfcName`, `bindingId`, REST URL, HTTP method, headers, token, or JSON payload mapping
- **THEN** the request is rejected or ignored before runtime execution
- **AND** no SAP, OData, CDS / ADT, or REST runtime call is triggered from those request-provided technical details

### Requirement: Multi-executor binding contract is expressible without runtime pilots
The system SHALL define schema-valid executor binding shapes for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` while only requiring the existing `JCO_RFC` inventory binding to execute in this change.

#### Scenario: Current JCO RFC binding remains valid
- **WHEN** the validator checks the current inventory binding for `MM.Inventory.GetAvailability`
- **THEN** the binding is accepted as `JCO_RFC`
- **AND** it maps to the existing allowlisted MD04 stock/requirements implementation without exposing arbitrary RFC execution

#### Scenario: Future executor binding shapes validate as contracts only
- **WHEN** schema examples or invalid-fixture tests cover `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON`
- **THEN** the schema can express their allowlisted binding metadata
- **AND** no OData Gateway, CDS / ADT Gateway, REST JSON Gateway, arbitrary HTTP client, arbitrary ADT SQL path, or runtime dispatcher is implemented by this change

### Requirement: REST JSON binding is controlled read-only contract readiness
The system SHALL model `REST_JSON` as a controlled executor binding for SAP-context external system facts, not as an open HTTP client.

#### Scenario: REST JSON contract stores only non-secret allowlist metadata
- **WHEN** a `REST_JSON` binding is represented by schema or fixture
- **THEN** it can express `systemRef`, fixed HTTP method, path template, request mapping, response mapping, credential reference, timeout, retry, and side-effect guard
- **AND** it does not store API keys, tokens, base URLs with secrets, tenant secrets, connection strings, raw headers with credentials, or arbitrary caller-provided payloads

#### Scenario: REST JSON Function cannot declare write side effects
- **WHEN** a `REST_JSON` binding is associated with a `Function`
- **THEN** the contract requires read-only side effect semantics
- **AND** any write-like REST operation or side-effecting business action must be modeled later as an `Action` with human approval outside this change

### Requirement: Governance consistency is enforced by contract validation
The system SHALL enforce governance consistency for capability kind, side effects, approval policy, data classification, and audit requirement before a capability can be treated as active.

#### Scenario: Function must be read-only and approval-free
- **WHEN** a capability has `kind=Function`
- **THEN** validation requires `sideEffect=none`, `requiresApproval=false`, and `approvalPolicy=not_required`

#### Scenario: Action must require human approval
- **WHEN** a capability has `kind=Action`
- **THEN** validation requires `requiresApproval=true` and `approvalPolicy=human_required`
- **AND** this change does not add or execute any SAP write Action

### Requirement: OWL skeleton provides stable capability identity
The system SHALL provide offline OWL skeleton files that define stable SAP Nexus core concepts and the MM inventory capability identity for future ontology governance without becoming a runtime dependency.

#### Scenario: Inventory capability maps to OWL identity
- **WHEN** the validator checks `MM.Inventory.GetAvailability`
- **THEN** the capability maps to stable ontology identity `sapnexus:MM_Inventory_GetAvailability`
- **AND** the referenced OWL skeleton contains the relevant SAP Nexus core and MM inventory terms needed for future migration

#### Scenario: OWL remains offline scaffolding
- **WHEN** the Agent, Workbench, Gateway, or eval regression runs
- **THEN** it does not require GraphDB, Jena, Neo4j, OWL runtime loading, or Graph Registry backend availability

### Requirement: Eval linkage is traceable for active capabilities
The system SHALL verify that active executable capabilities have matching regression coverage linking Registry contract, Agent behavior, Gateway behavior, and OpenSpec evidence.

#### Scenario: Inventory capability links to existing eval coverage
- **WHEN** the validator checks active capability `MM.Inventory.GetAvailability`
- **THEN** it finds matching Agent / Gateway regression coverage for the current inventory availability flow
- **AND** existing `scripts/verify-agent-callplan-evidence.sh` continues to pass without live LLM credentials or generated runtime traces

#### Scenario: Missing eval linkage fails validation
- **WHEN** an active capability lacks the required eval linkage metadata or matching regression case
- **THEN** contract validation fails before the capability can be considered release-ready

### Requirement: Registry v2 migration is atomic and runtime-compatible
The repository SHALL publish capability schema v2, capability Registry v2, Fact Type catalog, and semantic validators as one atomic change. It MUST NOT support a mixed v1/v2 Registry state or alter current technical executor ownership.

#### Scenario: Existing runtime loader reads migrated Registry
- **WHEN** the current Agent Registry loader reads the v2 document
- **THEN** it returns exactly the set of active capability IDs declared in the Registry and their current input descriptors
- **AND** the returned set and count are asserted against the Registry content rather than against a hardcoded number, so registering a capability changes the assertion input and not the assertion logic
- **AND** it does not copy planning metadata into the current CallPlan

#### Scenario: Technical binding ownership remains unchanged
- **WHEN** a migrated capability is validated or later selected by the current runtime
- **THEN** callers still provide only registered `capabilityId` and governed parameters
- **AND** `bindingId`, RFC/OData details, credentials, and executor mappings remain owned by allowlisted Registry/binding artifacts

### Requirement: Extraction declaration validation in registry contract

The registry contract validator SHALL validate intent-extraction declarations
on every active capability: matcher kind SHALL be one of the supported kinds;
keyword matchers with a constant `value` mapping and conditional
`when`/`requiredWhen` structures SHALL reference declared input fields with a
well-formed equality condition; `excludes` entries SHALL resolve to declared
input names of the same capability; `weakKeywords` SHALL be disjoint from
`primaryKeywords`; inline regex matchers SHALL compile successfully; regex
patterns SHALL be rejected when they exceed the backtracking-safety guard
(pattern length and nested-quantifier limits); every `semanticType` extraction
reference SHALL resolve to a published entry in the semantic-type extraction
catalog; and every required or conditionally required input SHALL carry a
`clarifyPrompt` covering the supported locales with well-formed
`cases`/`fallback` structure. A capability with malformed extraction
declarations SHALL fail validation before any runtime intent path can use it.

#### Scenario: Invalid regex rejected at load time

- **WHEN** a capability declares an input extraction matcher with a regex that
  does not compile or exceeds the backtracking-safety limits
- **THEN** registry contract validation fails with the offending capability and
  input identified

#### Scenario: Dangling semantic-type reference rejected

- **WHEN** an input extraction declaration references a `semanticType` that is
  not published in the semantic-type extraction catalog
- **THEN** registry contract validation fails before runtime use

#### Scenario: Missing clarify locale rejected

- **WHEN** a required input's `clarifyPrompt` omits a supported locale
- **THEN** registry contract validation fails for that capability

#### Scenario: Malformed condition or overlapping keyword tier rejected

- **WHEN** a `when`/`requiredWhen` condition references an undeclared input,
  an `excludes` entry does not resolve to a declared input name, or a keyword
  appears in both `primaryKeywords` and `weakKeywords`
- **THEN** registry contract validation fails with the offending capability
  and declaration identified

#### Scenario: Valid declarations pass

- **WHEN** all active capabilities carry well-formed extraction declarations
  that resolve against the catalog and cover required-input locales
- **THEN** registry contract validation succeeds

### Requirement: Semantic-type extraction catalog contract

The system SHALL treat `registry/semantic-types.yaml` as a versioned registry
artifact: each entry SHALL declare a semantic type identifier used as an
extraction reference key, at least one matcher, and an extraction priority;
entries SHALL be validated for regex compile/backtracking safety and duplicate
identifier rejection. The catalog SHALL be loaded atomically with the
capability registry so a snapshot always pairs capabilities with a consistent
catalog version, and gateway runtime behavior SHALL be unaffected by catalog
content (extraction metadata is agent-side).

#### Scenario: Duplicate catalog identifier rejected

- **WHEN** the catalog declares two entries with the same semantic type
  identifier
- **THEN** catalog validation fails

#### Scenario: Capability registry and catalog load as one snapshot

- **WHEN** the agent loads the registry for a governance snapshot
- **THEN** the capability declarations and the semantic-type catalog are
  resolved from the same load, so extraction references never cross catalog
  versions

#### Scenario: Gateway ignores extraction metadata safely

- **WHEN** the gateway loads a registry containing extraction declarations and
  a semantic-type catalog
- **THEN** gateway execution, validation, and governance behavior is unchanged
  compared to a registry without extraction metadata

### Requirement: Fact Type declares a field-level schema with resolved semantic types
The Fact Type catalog SHALL declare, for every published Fact Type, a field list in which each field declares `name`, `semanticType`, `cardinality` (`one` or `many`), `optional`, and `description`. A field's `semanticType` SHALL be drawn from the same ontology semantic-type vocabulary as capability input and output `semanticType` declarations and as the Fact Type `keyedBy` declaration, and SHALL NOT be drawn from the extraction matcher catalog, whose identifiers occupy a separate namespace. A field's `semanticType` MUST appear as the `semanticType` of at least one capability input or output in the same governed source set; a Fact Type field declaring a semantic type no capability speaks SHALL fail contract validation, because such a field can never participate in a derived data dependency. The field list SHALL be the single authoritative definition of that Fact Type's shape: no other artifact may introduce, rename, or remove a Fact Type field, and any artifact that restates the field list SHALL be validated against the authoritative list.

#### Scenario: Field list with resolved semantic types validates
- **WHEN** the contract validator checks a published Fact Type whose every field declares a `name`, a `semanticType` that some capability input or output also declares, a `cardinality` of `one` or `many`, an `optional` flag, and a `description`
- **THEN** contract validation succeeds for that Fact Type

#### Scenario: Semantic type unknown to every capability fails validation
- **WHEN** a Fact Type field declares a `semanticType` that no capability input or output declares
- **THEN** contract validation fails and names the offending Fact Type and field
- **AND** no semantic graph or Registry Snapshot is published from that catalog

#### Scenario: Matcher catalog identifier on a field fails validation
- **WHEN** a Fact Type field declares a `semanticType` taken from the extraction matcher catalog namespace instead of the ontology vocabulary
- **THEN** contract validation fails and names the offending Fact Type and field
- **AND** the failure is not silently tolerated as an unmatched-but-valid declaration

#### Scenario: Field list without required attributes fails validation
- **WHEN** a Fact Type field omits `name`, `semanticType`, `cardinality`, `optional`, or `description`, or declares a `cardinality` outside `one|many`
- **THEN** contract validation fails with a deterministic error identifying the field

#### Scenario: Restated field list must match the authoritative definition
- **WHEN** another governed or presentation artifact restates the field names of a published Fact Type
- **THEN** a conformance check compares the restatement against the authoritative field list
- **AND** the check fails when a restated name is absent from, or missing relative to, the authoritative list

### Requirement: The extraction matcher catalog maps one-way onto the ontology vocabulary
The extraction matcher catalog is the source of utterance-extraction matchers, not the authority for semantic types. Each matcher entry SHALL declare `extracts` naming exactly one ontology semantic type, and SHALL NOT declare that it extracts two or more different ontology types. One ontology semantic type MAY be extracted by several matcher entries, and MAY be extracted by none — a value obtainable only from the system legitimately has no extractor, and the absence of a matcher entry SHALL NOT be treated as a catalog defect to be back-filled. The mapping is one-way: the ontology vocabulary SHALL NOT reference matcher identifiers. Contract validation SHALL reject any `sapnexus:` reference that does not exist in the ontology vocabulary, and SHALL reject any `extracts` target that does not exist in the ontology vocabulary.

#### Scenario: One-way mapping validates
- **WHEN** every matcher entry declares an `extracts` target that exists in the ontology vocabulary
- **THEN** contract validation succeeds
- **AND** an ontology semantic type with several matcher entries is accepted
- **AND** an ontology semantic type with no matcher entry is accepted without a warning that requires back-filling

#### Scenario: A matcher extracting two ontology types is rejected
- **WHEN** a matcher entry declares that it extracts two or more different ontology semantic types
- **THEN** contract validation fails and names the offending matcher entry

#### Scenario: Unresolvable reference is rejected on either side
- **WHEN** a `sapnexus:` reference names a semantic type absent from the ontology vocabulary, or an `extracts` target names a semantic type absent from the ontology vocabulary
- **THEN** contract validation fails and names the offending reference and its declaring entry
- **AND** no semantic graph or Registry Snapshot is published

### Requirement: A newly registered capability requires no non-registry code change
Registering an additional capability SHALL require changes only to governed registry, binding, ontology, and eval-linkage artifacts. The intent, recall, planning, and narration layers MUST NOT require capability-specific code for a capability to be validated, recalled, planned, and narrated. Where a presentation-layer declaration is unavoidable, it SHALL be reported explicitly rather than treated as registry work.

#### Scenario: Fourth capability is registered without agent-layer code changes
- **WHEN** `MM.Material.GetInfo` is registered as `status: active` with inputs, outputs, executor binding, governance, and eval linkage
- **THEN** contract validation, capability recall, and plan authoring accept it with no capability-specific branch added to the intent, recall, planning, or narration layers
- **AND** the count of non-registry lines required for registration is reported, and pre-existing defects exposed by the registration are reported as a separate figure with their own attribution

#### Scenario: Read capability registration cannot introduce write semantics
- **WHEN** an added capability declares `kind=Function` with `sideEffect=none`
- **THEN** validation rejects any binding that would commit or roll back an SAP transaction for that capability
- **AND** the capability cannot require or consume a human approval record

