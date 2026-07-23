# SAP Nexus Gateway

SAP Nexus Gateway is the capability-level SAP execution boundary for SAP Nexus
Agent. It exposes registered capabilities only; callers use `capabilityId`,
never arbitrary RFC names, OData service URLs, or raw HTTP endpoints.

The Gateway is a multi-module Java Spring Boot project that routes by executor
type to the appropriate `TechnicalAdapter`. Currently two executor families are
wired in:

- `JCO_RFC` -- `JcoRfcTechnicalAdapter` calls SAP BAPI/RFC directly via JCo.
- `ODATA` -- `ODataHttpProxyAdapter` is a thin reverse proxy that forwards to
  the Python OData microservice (`services/odata-service/`, :8081) and
  normalizes the JSON response into `TechnicalExecutionResult`.

Unsupported executor types (`CDS_ADT`, `CDS_ODATA`, `REST_JSON`, `SQL_READ`)
are fail-closed: the dispatcher returns `UNSUPPORTED_EXECUTOR`.

## Module Structure

```text
services/gateway/
├── settings.gradle          rootProject.name = sap-nexus-gateway; includes core, jco, odata, app
├── gradlew                  Gradle Wrapper
├── core/                    Shared contracts: TechnicalExecutionRequest / TechnicalExecutionResult,
│                            TechnicalExecutionDispatcher, TechnicalAdapter interface,
│                            TechnicalRedactor, Trace, CapabilityRegistry / BindingRegistry,
│                            CapabilityController (REST endpoints)
├── jco/                     JCo connector: JcoRfcTechnicalAdapter + JCo destination
│   └── lib/                 sapjco3.jar + native libs (linux/windows/macos)
├── odata/                   OData thin reverse proxy: ODataHttpProxyAdapter + ODataProxyProperties
└── app/                     Spring Boot bootstrap: SapNexusGatewayApplication + application.yml
```

Dependency direction: `app` depends on `jco` + `odata` + `core`; `jco` and
`odata` depend on `core`; `core` has no dependencies on sibling connector
modules. This keeps the shared contract in `core` and each connector isolated.

## Scope

Implemented API surface:

```text
GET  /health
GET  /capabilities
POST /capabilities/{capabilityId}/validate
POST /capabilities/{capabilityId}/execute
```

Forbidden API surface:

```text
POST /rfc/{rfcName}/execute
POST /execute with request-provided rfcName
POST /odata/{service}/execute with request-provided service URL
```

The Gateway never accepts `rfcName`, OData service URL, binding ID, or any
technical override from the caller. These come exclusively from the registry.

## Implementation Rules

- **Capability-level boundary**: the Gateway only exposes registered
  capabilities. Callers use `capabilityId`; the internal flow is
  `CapabilityController` (rejects technical override) -> `validate` -> fetch
  capability -> `TechnicalExecutionRequest` (bindingId + parameters, no
  technical details) -> `TechnicalExecutionDispatcher` routes by
  `executorType` -> `TechnicalAdapter` -> `TechnicalExecutionResult` ->
  `toExecutionResult(capability)`.
- **Dispatcher routing**: `TechnicalExecutionDispatcher` is a Spring Bean
  injected with `Map<String, TechnicalAdapter>`, keyed by bean name
  (= executor type string). Each adapter declares
  `@Component("<EXECUTOR_TYPE>")` and auto-registers into the dispatcher.
- **Fail-closed**: unimplemented executor types return `UNSUPPORTED_EXECUTOR`.
  Currently `CDS_ADT` / `CDS_ODATA` / `REST_JSON` / `SQL_READ` are fail-closed.
- **Redaction**: `TechnicalRedactor` redacts destination / token / cookie /
  credential at the technical execution boundary before any result or trace
  leaves the Gateway.
- **READ safety**: READ capabilities must not call
  `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`.
- **WRITE safety**: WRITE capabilities must not execute until Human Approval
  is confirmed for that capability (sandbox write pilot pending).
- **OData thin proxy pattern**: for executor families that are pure HTTP with
  no Java SDK binding (like OData), the Java adapter is a thin reverse proxy
  -- it does HTTP forwarding + JSON normalization to
  `TechnicalExecutionResult` + redaction. It does not assemble `$filter`,
  connect to SAP directly, or hold OData protocol logic. The real logic lives
  in the Python microservice (`services/odata-service/`). This contrasts with
  JCo, where `sapjco3.jar` mandates a Java binding and the adapter implements
  execution directly.

## Extension Rules

To add a new executor family (e.g. `CDS_ADT`, `REST_JSON`, `SQL_READ`):

1. **Registry**:
   - Add a binding to `registry/executor-bindings.yaml`
     (`type: <NEW_EXECUTOR_TYPE>`, with the corresponding metadata fields).
   - Add a capability to `registry/capabilities.yaml`
     (`executorBinding.type` aligned to the new type).
   - Update `schemas/executor-binding.schema.json` and
     `schemas/capability.schema.json` with conditional `required` branches for
     the new type.
2. **Gateway adapter**: create `<Executor>TechnicalAdapter` (implements
   `TechnicalAdapter`) under `services/gateway/<executor>/`, declared as
   `@Component("<EXECUTOR_TYPE>")` so it auto-registers into the dispatcher.
   - If the executor is pure HTTP / has no Java SDK (like OData / REST):
     follow the OData pattern -- Java side is a thin reverse-proxy adapter +
     Python service (`services/<executor>-service/`) does the real work; Java
     adapter does HTTP forwarding + JSON normalization + redaction.
   - If the executor has a Java SDK (like JCo): the Java adapter implements
     execution directly.
3. **Binding metadata access**: the adapter injects `CapabilityRegistry` +
   `BindingRegistry` and fetches binding metadata by `bindingId` itself. The
   `TechnicalExecutionRequest` contract does not change -- it only carries
   `bindingId` + `parameters`.
4. **`toExecutionResult` decoupling**: the adapter constructs
   `TechnicalExecutionResult.success(...)` / `.failure(...)` directly (do not
   use `fromExecutionResult`, because `Map.of` does not allow null; when a new
   executor has no `rfcName`, fill `null`).
5. **Request ownership guard**: add the new executor's technical-override key
   detection to `CapabilityRequest.collectTechnicalOverride`.
6. **Tests**: adapter mock tests + dispatcher routing integration tests +
   JCo / existing regression.
7. **Agent side**: no changes needed. The Agent only knows `capabilityId`;
   the selector intent->capabilityId mapping table is the single integration
   point and does not need to be aware of executor types.

## Official SAP JCo Libraries

This project uses SAP official JCo files copied from the already validated
reference implementation:

```text
sap-skill-create/skills-production/sap-sto-create/scripts/lib/java
```

Gateway-local layout:

```text
services/gateway/jco/lib/sapjco3.jar
services/gateway/jco/lib/linux/libsapjco3.so
services/gateway/jco/lib/windows/sapjco3.dll
services/gateway/jco/lib/macos/.gitkeep
```

`build.gradle` references `lib/sapjco3.jar` through a local file dependency.
Linux live smoke tests should set `SAP_JCO_LIB_PATH` to
`services/gateway/jco/lib/linux` or another directory containing
`libsapjco3.so`.

## Environment

Create `.env` in the repository root from `.env.example`. The real `.env` is
ignored by git.

Required for SAP JCo destination (inventory capability):

```bash
SAP_ASHOST=sap.example.local
SAP_SYSNR=00
SAP_CLIENT=100
SAP_USER=YOUR_SAP_USER
SAP_PASSWORD=YOUR_SAP_PASSWORD
SAP_LANG=ZH
SAP_JCO_LIB_PATH=/absolute/path/to/sap-nexus-agent/services/gateway/jco/lib/linux
```

Required for SAP OData (PO capability, consumed by Python microservice):

```bash
SAP_URL=https://sap.example.local:44300
SAP_SAPCLIENT=100
SAP_USER=YOUR_SAP_USER
SAP_PASSWORD=YOUR_SAP_PASSWORD
```

Optional:

```bash
SAP_SAPROUTER=/H/router.example.local/S/3299
```

Do not add unrelated SAP HTTP URLs or real credentials to committed files.

## Fast Verification

Fast tests do not require SAP connectivity:

```bash
cd services/gateway
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 GRADLE_USER_HOME=/tmp/gradle-home /tmp/gradle-8.8/bin/gradle --no-daemon test
```

If the Gradle Wrapper distribution is already available locally, this
equivalent command is expected to work:

```bash
cd services/gateway
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ./gradlew --no-daemon test
```

Expected: 79 tests pass (JCo adapter + OData thin proxy + dispatcher routing
+ controller + redactor + registry + regression).

OData microservice tests (run from `services/odata-service/`):

```bash
PYTHONPATH=. python -m pytest tests/ -v
```

Expected: 26 passed, 5 skipped (skipped tests require live SAP connectivity).

## Local Run

From `services/gateway/`, load root `.env` and start the Gateway:

```bash
set -a
. ../.env
set +a
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
GRADLE_USER_HOME=/tmp/gradle-home \
/tmp/gradle-8.8/bin/gradle --no-daemon bootRun
```

`bootRun` passes `SAP_JCO_LIB_PATH` into `java.library.path` for the official
native JCo library. The Gateway listens on `:8080`.

For OData capabilities, also start the Python OData microservice in a separate
terminal:

```bash
cd services/odata-service
PYTHONPATH=. python -m odata_service.server   # listens on :8081
```

## Live Smoke Checks

In another shell after the Gateway starts:

```bash
curl -s http://localhost:8080/health
curl -s http://localhost:8080/capabilities
curl -s -X POST http://localhost:8080/capabilities/MM.Inventory.GetAvailability/validate \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{"material":"MAT-001","plant":"1000","unit":"EA"}}'
```

Live execute reaches SAP through JCo and should only be run with known-safe
read parameters:

```bash
curl -s -X POST http://localhost:8080/capabilities/MM.Inventory.GetAvailability/execute \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{"material":"MAT-001","plant":"1000","unit":"EA"}}'
```

`MM.Inventory.GetAvailability` is a READ Function. It must not call
`BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`.

PO OData capability (`MM.PurchaseOrder.GetList`) is active after live SAP ICF
(SICF) service enablement. Smoke check:

```bash
curl -s -X POST http://localhost:8080/capabilities/MM.PurchaseOrder.GetList/validate \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{"vendor":"DEMOV1"}}'

curl -s -X POST http://localhost:8080/capabilities/MM.PurchaseOrder.GetList/execute \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{"vendor":"DEMOV1"}}'
```

The OData execution path is: Gateway dispatcher -> `ODataHttpProxyAdapter`
(thin proxy) -> Python OData microservice (:8081) -> SAP OData service. The
Gateway does not assemble `$filter` or connect to SAP directly for OData.

## Runtime Trace

Validate and execute operations append JSONL trace records to:

```text
../runtime/gateway-jco/traces.jsonl
```

Trace records include `traceId`, `timestamp`, `operation`, `capabilityId`,
`parameterSummary`, `success`, `durationMs`, and `errorType`. They must not
include SAP passwords, tokens, full destination properties, or `.env`
contents.
