## ADDED Requirements

### Requirement: Technical execution requests are binding-owned

The Gateway MUST create technical execution requests from registered capability and executor binding metadata, not from caller-owned raw technical details.

#### Scenario: Build request from registered binding

- **WHEN** a valid capability execution request is accepted for `MM.Inventory.GetAvailability`
- **THEN** the Gateway creates a technical execution request using the capability's registered `executorBinding.bindingId`
- **AND** the request identifies the allowlisted executor type and normalized parameters needed by the adapter
- **AND** the request does not use caller-provided `rfcName`, URL, header, credential, SQL, or payload-mapping fields

#### Scenario: Reject raw technical override

- **WHEN** a caller includes `rfcName`, service URL, CDS object, ADT path, REST endpoint, HTTP method, headers, `credentialRef`, JSON mapping, raw SQL, or equivalent technical override fields
- **THEN** the Gateway rejects or ignores those fields before adapter execution
- **AND** SAP or external execution is not attempted with caller-owned technical details

### Requirement: Dispatcher executes only allowlisted bindings

The Gateway MUST resolve technical execution through a closed dispatcher that maps registered `bindingId` and executor type to an allowed adapter.

#### Scenario: Dispatch current JCO_RFC binding

- **WHEN** the registered inventory binding resolves to executor type `JCO_RFC`
- **THEN** the dispatcher invokes the controlled JCo adapter for the current inventory read path
- **AND** the adapter uses the registered binding metadata rather than arbitrary runtime RFC selection

#### Scenario: Fail closed for unsupported future executor

- **WHEN** a registered binding uses `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`, or another contract-recognized executor without an implemented runtime adapter in this change
- **THEN** the dispatcher returns a deterministic fail-closed technical result
- **AND** the Gateway does not attempt arbitrary HTTP, ADT, CDS, REST, SQL, or RFC execution

### Requirement: Technical results remain compatible with capability execution

The Gateway MUST normalize adapter output into a technical execution result that remains convertible to the current capability-level `ExecutionResult`.

#### Scenario: Preserve Agent-facing execution result

- **WHEN** `MM.Inventory.GetAvailability` executes successfully through the binding dispatcher
- **THEN** the capability-level response preserves the current `ExecutionResult` fields expected by the Python Agent and Workbench
- **AND** existing `ReasoningFact` generation and Agent regression behavior remain unchanged

#### Scenario: Normalize technical failure

- **WHEN** adapter execution fails because of SAP communication, SAP authorization, SAP business error, unsupported executor type, or normalization failure
- **THEN** the technical result records `traceId`, `bindingId`, executor type, success state, error type, messages, duration, and redaction status
- **AND** the converted capability-level result uses deterministic error semantics compatible with the current Gateway API

### Requirement: Technical traces and errors are redacted

The Gateway MUST apply sensitive-data redaction at the technical execution boundary and in trace records.

#### Scenario: Redact sensitive technical details

- **WHEN** a technical request, result, trace, or error contains destination config, SAP password, `.env` content, token, LLM API key, raw credential, sensitive endpoint, header secret, or credential reference material
- **THEN** the Gateway redacts the sensitive value before returning or writing trace output
- **AND** verification can prove no sensitive value is exposed through normal response, trace, or error paths
