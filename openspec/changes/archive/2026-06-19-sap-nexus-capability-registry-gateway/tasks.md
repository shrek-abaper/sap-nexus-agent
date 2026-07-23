## 1. Registry And Contracts

- [x] 1.1 Create `registry/capabilities.yaml` with `MM.Inventory.GetAvailability` as an active `Function` mapped to `BAPI_MATERIAL_AVAILABILITY`.
- [x] 1.2 Add `schemas/capability.schema.json` covering identity, kind, status, semantic metadata, inputs, outputs, executor, governance, side effects, and approval policy.
- [x] 1.3 Add `schemas/execution-result.schema.json` for normalized Gateway responses including traceId, capabilityId, executor metadata, return messages, data, duration, success state, and error type.
- [x] 1.4 Add generated runtime output ignore rules for traces, callplans, facts, eval results, and local Gateway runtime files.

## 2. Java Gateway Skeleton

- [x] 2.1 Create `gateway-jco/` Spring Boot + Gradle Wrapper project structure targeting Java 17, or document a temporary Java 11 compatibility decision before implementation.
- [x] 2.2 Add Gateway README with build/test commands, local SAP/JCo prerequisites, and live smoke test prerequisites.
- [x] 2.3 Add application package structure for API, capability registry, validation, JCo adapter, result normalization, and trace emission.
- [x] 2.4 Implement `GET /health` returning Gateway/JCo readiness fields without exposing SAP credentials or sensitive destination details.

## 3. Capability Registry Loading And Validation

- [x] 3.1 Implement Registry loader that reads `registry/capabilities.yaml` and exposes enabled capabilities in memory.
- [x] 3.2 Implement registry validation for required fields, duplicate capability IDs, valid kind, Function side-effect constraints, and Action approval constraints.
- [x] 3.3 Implement `GET /capabilities` returning enabled registered capabilities from the Registry rather than hardcoded controller data.
- [x] 3.4 Add tests for valid registry load, malformed registry rejection, duplicate capability IDs, and disabled capability exclusion.

## 4. Validate And Execute APIs

- [x] 4.1 Implement `POST /capabilities/{capabilityId}/validate` with unknown capability, disabled capability, missing required parameter, and invalid parameter handling.
- [x] 4.2 Ensure validation failures return structured error types and never invoke SAP JCo.
- [x] 4.3 Implement `POST /capabilities/{capabilityId}/execute` for registered READ Functions, including validate-before-execute behavior.
- [x] 4.4 Ensure the Gateway has no arbitrary RFC execution endpoint and does not allow request payloads to override `executor.rfcName`.

## 5. JCo Execution And Result Normalization

- [x] 5.1 Implement JCo destination configuration using SAP environment variable conventions and `SAP_JCO_LIB_PATH` support.
- [x] 5.2 Implement `MM.Inventory.GetAvailability` executor path that maps Registry inputs to `BAPI_MATERIAL_AVAILABILITY` parameters.
- [x] 5.3 Normalize SAP `RETURN` messages and map SAP business, auth, and communication failures to structured error types.
- [x] 5.4 Return normalized `ExecutionResult` without SAP credentials, full destination details, or sensitive environment values.
- [x] 5.5 Ensure READ Function execution does not call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`.

## 6. Trace And Verification

- [x] 6.1 Implement JSONL trace emission for validate and execute operations under an ignored runtime path.
- [x] 6.2 Add tests or checks confirming trace records include traceId, operation, capabilityId, parameter summary, success, duration, and errorType while excluding secrets.
- [x] 6.3 Add fast verification commands for schema/registry validation and Gateway unit tests.
- [x] 6.4 Add documented live SAP smoke commands for `/health`, `/capabilities`, validate, and execute, separated from fast tests.
- [x] 6.5 Run the relevant verification commands and record results before marking this change ready for verify.

<!-- review completed: subagent review found 4 Important issues; all were fixed and re-verified before verify -->
