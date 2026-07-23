# registry-ontology-contract Specification

## Purpose
Define the release-gate contract for SAP Nexus Capability Registry semantics, executor binding readiness, governance consistency, OWL skeleton identity, eval linkage, and controlled multi-executor binding shapes without introducing runtime Gateway pilots or Knowledge Graph dependencies.
## Requirements
### Requirement: Registry schema validates semantic capability contract
The system SHALL validate `registry/capabilities.yaml` version `2` against a deterministic Registry contract that covers capability identity, semantic metadata, typed inputs, Fact-producing outputs, governance, and executor binding references. Every input MUST declare `bindingKind=identifier|fact`; a fact-bound input MUST reference one published `satisfiableByFactType`, while an identifier input MUST NOT declare that field. Every output with `evidenceRole=primaryFact` MUST reference one published `factTypeRef`.

#### Scenario: All active capabilities pass Registry v2 contract
- **WHEN** the contract validator checks the active `MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`, and `MM.PR.CreateDraft` entries
- **THEN** validation succeeds for their stable identity, semantic IO, governance, eval linkage, and executor binding references
- **AND** each existing input is classified as `bindingKind=identifier`
- **AND** their primary outputs reference `sapnexus:InventoryAvailabilityFact`, `sapnexus:PurchaseOrderSupplyFact`, and `sapnexus:PurchaseRequisitionCreatedFact` respectively
- **AND** the capabilities remain available to existing Agent and Gateway flows by the same `capabilityId`

#### Scenario: Fact-bound input lacks Fact Type reference
- **WHEN** an input declares `bindingKind=fact` without `satisfiableByFactType`
- **THEN** contract validation fails before graph compilation or runtime execution

#### Scenario: Identifier input declares Fact Type reference
- **WHEN** an input declares `bindingKind=identifier` together with `satisfiableByFactType`
- **THEN** contract validation fails as contradictory parameter provenance

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
- **THEN** it returns the same three active capability IDs and current input descriptors
- **AND** it does not copy planning metadata into the current CallPlan

#### Scenario: Technical binding ownership remains unchanged
- **WHEN** a migrated capability is validated or later selected by the current runtime
- **THEN** callers still provide only registered `capabilityId` and governed parameters
- **AND** `bindingId`, RFC/OData details, credentials, and executor mappings remain owned by allowlisted Registry/binding artifacts
