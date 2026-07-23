## MODIFIED Requirements

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

## ADDED Requirements

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
