## MODIFIED Requirements

### Requirement: Dispatcher executes only allowlisted bindings

The Gateway MUST resolve technical execution through a closed dispatcher that maps registered `bindingId` and executor type to an allowed adapter. The dispatcher SHALL route `JCO_RFC` bindings to the JCo adapter and `ODATA` bindings to the OData adapter; contract-recognized executor types without an implemented runtime adapter MUST fail closed.

#### Scenario: Dispatch current JCO_RFC binding

- **WHEN** the registered inventory binding resolves to executor type `JCO_RFC`
- **THEN** the dispatcher invokes the controlled JCo adapter for the current inventory read path
- **AND** the adapter uses the registered binding metadata rather than arbitrary runtime RFC selection

#### Scenario: Dispatch ODATA binding to OData adapter

- **WHEN** the registered purchase order binding resolves to executor type `ODATA`
- **THEN** the dispatcher invokes the controlled OData adapter for the registered `serviceRef` and `entitySet`
- **AND** the adapter uses the registered binding metadata rather than arbitrary runtime OData URL or endpoint selection
- **AND** the OData adapter normalizes the response into the same technical execution result contract used by the JCo adapter

#### Scenario: Fail closed for unsupported future executor

- **WHEN** a registered binding uses `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, `SQL_READ`, or another contract-recognized executor without an implemented runtime adapter in this change
- **THEN** the dispatcher returns a deterministic fail-closed technical result
- **AND** the Gateway does not attempt arbitrary HTTP, ADT, CDS, REST, SQL, or RFC execution
