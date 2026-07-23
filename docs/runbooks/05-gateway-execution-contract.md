# Gateway Execution Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `05-gateway-execution-contract` |
| Version | `v0.2.1` |
| Status | `Archived` |
| Created | `2026-06-25` |
| Updated | `2026-06-28` |
| Workstream | Unified technical execution request/result, binding dispatcher contract, JCo binding readiness, and Gateway redaction / trace consistency |
| Related Change | `sap-nexus-gateway-execution-contract` |
| Current Phase | Completed, verified, and archived |

---

## 1. Session Goal

Start the next OpenSpec / Comet change after Registry / OWL contract hardening:

```text
sap-nexus-gateway-execution-contract
```

Target product path:

```text
Capability Registry YAML
-> Semantic capability / technical binding split
-> Executor Binding Catalog
-> TechnicalExecutionRequest
-> bindingId dispatcher
-> protocol adapter execution
-> TechnicalExecutionResult
-> normalized ExecutionResult compatibility
-> TraceSpan / redaction consistency
-> Agent / ReasoningFact behavior unchanged
-> OpenSpec / traceable verification evidence
```

This workstream defines the Gateway technical execution contract before any OData, CDS / ADT, or REST JSON runtime pilot.

Do not repeat Gateway / Registry execution baseline, Python Agent CallPlan, LLM intent adapter, Workbench Console, MD04 inventory BAPI correction, or Registry / OWL contract hardening unless a concrete regression is found.

---

## 2. Expected Baseline Before Starting This Workstream

Expected completed and archived changes:

```text
sap-nexus-capability-registry-gateway -> completed, verified, archived
sap-nexus-agent-callplan-evidence -> completed, verified, archived
sap-nexus-agent-llm-intent-adapter -> completed, verified, archived
sap-nexus-agent-workbench-console -> completed, verified, archived
sap-nexus-workbench-live-agent-runtime -> completed, verified, archived
sap-nexus-inventory-md04-stock-req-list -> completed, verified, archived
sap-nexus-registry-ontology-contract -> completed, verified, archived
```

Main specs:

```text
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/agent-callplan-evidence/spec.md
openspec/specs/agent-workbench-console/spec.md
openspec/specs/registry-ontology-contract/spec.md
```

Key implemented artifacts from the prior workstream:

- `registry/capabilities.yaml` keeps the active `MM.Inventory.GetAvailability` semantic capability and runtime-compatible `executor` block.
- `registry/capabilities.yaml` also has `executorBinding.bindingId=sap.mm.inventory.md04-stock-req-list` and eval linkage.
- `registry/executor-bindings.yaml` defines the current allowlisted `JCO_RFC` binding.
- `schemas/executor-binding.schema.json` defines contract-ready shapes for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON`.
- `scripts/validate-registry-contract.py` validates Registry / OWL / governance / eval linkage consistency.
- `ontology/` contains offline OWL skeleton identity only; no runtime graph dependency exists.
- `agent/tests/test_registry_contract.py` covers positive and negative Registry contract cases.

Verified baseline commands after archive:

```text
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
-> Registry contract valid: registry/capabilities.yaml

.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
-> 13 passed

scripts/verify-agent-callplan-evidence.sh
-> 54 passed, 1 skipped
-> Eval passed: 7/7
-> openspec validate --all --strict: 4 passed, 0 failed

openspec list --json
-> {"changes":[]}
```

OpenSpec may print PostHog telemetry network errors after valid command output. Treat those as non-blocking if the command exits successfully and validation output is passed.

---

## 3. Start Checklist

Run these before opening or changing anything:

```bash
git status --short
openspec list --json
openspec validate --all --strict
scripts/verify-agent-callplan-evidence.sh
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
```

Read these source-of-truth docs:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/05-gateway-execution-contract.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/agent-callplan-evidence/spec.md
openspec/specs/registry-ontology-contract/spec.md
registry/README.md
ontology/README.md
```

Expected state:

- Current branch is expected to be `main` unless the user explicitly changes it.
- `openspec list --json` should show no active changes before this workstream starts.
- `git status --short` should be clean or contain only user-confirmed local edits.
- Registry / OWL contract is already complete; do not reopen it unless this workstream finds a concrete compatibility gap.

---

## 4. Proposed Workstream Scope

Build only the technical execution contract layer for Gateway family readiness.

In scope:

- Define `TechnicalExecutionRequest` for allowlisted technical execution by `bindingId`.
- Define `TechnicalExecutionResult` as the protocol-adapter result before / during conversion to current `ExecutionResult`.
- Define `bindingId -> technical adapter` dispatcher boundary.
- Adapt the current JCo inventory execution path to the binding contract, while preserving the existing capability-level API as a compatibility facade if needed.
- Keep Agent-facing `ExecutionResult` and `ReasoningFact` behavior unchanged.
- Keep existing `MM.Inventory.GetAvailability` behavior unchanged.
- Add schema and tests for technical execution request/result contracts.
- Add negative tests proving callers cannot provide or override raw `rfcName`, OData URL/service, CDS object/path, REST endpoint, HTTP method, headers, credentialRef, or JSON payload mapping.
- Unify technical error types, return messages, duration, trace identifiers, and sensitive redaction rules at the technical execution boundary.
- Document the transition path from capability-level execution to binding-level execution.

Out of scope:

- New SAP capability.
- OData Gateway runtime implementation.
- CDS / ADT Gateway runtime implementation.
- REST JSON Gateway runtime implementation.
- Arbitrary HTTP client, arbitrary URL execution, arbitrary ADT SQL, or arbitrary RFC execution.
- STO creation or any SAP write action.
- SAP Write Action, Human Approval runtime changes, RecommendationPlan, ML uncertainty reasoning, UI, or multi-domain orchestration.
- Knowledge Graph runtime or Graph Registry backend.
- LLM-generated JSON payload execution or LLM-generated technical execution details.

---

## 5. Suggested Artifact Shape

Prefer a minimal, compatibility-first contract. Exact placement can change if the existing Java Gateway structure suggests a better local fit.

```text
gateway-jco/src/main/java/.../execution/
  TechnicalExecutionRequest.java
  TechnicalExecutionResult.java
  TechnicalExecutionDispatcher.java
  TechnicalAdapter.java
  JcoRfcTechnicalAdapter.java

gateway-jco/src/test/java/.../execution/
  TechnicalExecutionContractTest.java
  TechnicalExecutionDispatcherTest.java

schemas/
  technical-execution-request.schema.json
  technical-execution-result.schema.json

registry/
  executor-bindings.yaml

scripts/
  validate-registry-contract.py   # keep existing; extend only if contract linkage requires it
```

Compatibility principle:

```text
Existing API: POST /capabilities/{capabilityId}/validate|execute
-> semantic lookup / compatibility facade
-> executorBinding.bindingId
-> TechnicalExecutionRequest
-> dispatcher
-> JCO_RFC adapter
-> TechnicalExecutionResult
-> current ExecutionResult shape
```

Future API, not necessarily required in this change:

```text
POST /bindings/{bindingId}/execute
```

Do not expose future binding-level API until request ownership, redaction, and compatibility behavior are proven by tests.

---

## 6. Contract Model Notes

### TechnicalExecutionRequest

The request should identify only an allowlisted binding and already-normalized technical inputs:

```text
traceId
bindingId
executorType
operation
parameters
constraints
callerContext
```

Request-owned technical details remain forbidden:

```text
rfcName
odataUrl
serviceUrl
cdsViewName
adtPath
restUrl
httpMethod
headers
credentialRef override
rawJsonPayload mapping override
```

### TechnicalExecutionResult

The result should preserve technical evidence without leaking credentials:

```text
traceId
bindingId
executorType
success
errorType
messages
data
durationMs
redactionApplied
adapterMetadata
```

It must remain convertible to the current `ExecutionResult` expected by Python Agent and `ReasoningFact` logic.

### Dispatcher

The dispatcher should be a closed set:

```text
JCO_RFC -> current Java JCo adapter
ODATA -> not implemented in this change
CDS_ADT -> not implemented in this change
CDS_ODATA -> not implemented in this change
REST_JSON -> not implemented in this change
```

Unsupported executor types should fail closed with deterministic errors, not fall through to arbitrary execution.

---

## 7. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Contract | `TechnicalExecutionRequest` and `TechnicalExecutionResult` have explicit schemas or Java types with tests |
| Dispatcher | `bindingId` resolves only to allowlisted Registry / binding catalog entries |
| JCo compatibility | Existing `MM.Inventory.GetAvailability` still executes through the current JCo implementation path |
| Agent compatibility | Existing Agent CallPlan / Evidence regression still passes unchanged |
| Request ownership | External callers cannot submit or override `rfcName`, service URL, CDS object, ADT path, REST endpoint, HTTP method, headers, credentialRef, or JSON mapping |
| Future executor readiness | `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` are recognized as contract types but fail closed without runtime pilots |
| Redaction | Technical result, trace, and errors do not expose `.env`, SAP password, destination config, token, LLM API key, raw credential, or sensitive endpoint |
| OpenSpec | Change has proposal, design, tasks, delta spec, verification evidence, and archive path |

Recommended verification command shape after implementation:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
# plus the relevant gateway-jco test command documented by the change
```

Adjust exact Gateway test commands to match the final Java build setup.

---

## 8. Safety And Workflow Notes

- Do not create or switch branches unless the user explicitly asks.
- Do not commit unless explicitly asked or the Comet finishing step requires and the user confirms.
- Do not commit `.env`, SAP passwords, destination config, token, LLM API key, or runtime traces.
- Do not print SAP passwords or full destination configuration.
- Do not add arbitrary RFC execution to Agent or Gateway.
- Do not add arbitrary OData / CDS / ADT / REST execution to Agent or Gateway.
- Do not let LLM output create or override `bindingId`, `rfcName`, REST URL, HTTP method, headers, token, credentialRef, or JSON payload mapping.
- Do not implement OData Gateway, CDS / ADT Gateway, or REST JSON Gateway runtime in this change.
- Do not introduce Knowledge Graph runtime dependency.
- Treat `REST_JSON` as contract readiness only until a separate REST JSON read pilot is opened.

---

## 9. Recommended First Steps

1. Open a new OpenSpec / Comet change named `sap-nexus-gateway-execution-contract`.
2. Design `TechnicalExecutionRequest`, `TechnicalExecutionResult`, dispatcher behavior, and compatibility facade before writing implementation code.
3. Inspect `gateway-jco/` loader, validator, executor, trace, and result normalization code to identify the smallest compatibility-safe insertion point.
4. Add failing tests for request-owned technical override rejection and unsupported future executor fail-closed behavior.
5. Adapt the existing `JCO_RFC` inventory execution path to the new contract without changing Agent-facing output.
6. Run Gateway tests, Registry contract validation, Agent regression, and OpenSpec strict validation before verify / archive.

---

## 10. Prompt To Start The Next Session

```text
继续 . 项目工作。

请先读取并遵守：
1. AGENTS.md
2. docs/runbooks/README.md
3. docs/runbooks/05-gateway-execution-contract.md
4. docs/wiki/sap-nexus-agent-technical-architecture.md
5. docs/wiki/sap-nexus-agent-implementation-roadmap.md
6. openspec/specs/capability-registry-gateway/spec.md
7. openspec/specs/agent-callplan-evidence/spec.md
8. openspec/specs/registry-ontology-contract/spec.md

当前状态：
- sap-nexus-capability-registry-gateway 已完成、验证并归档。
- sap-nexus-agent-callplan-evidence 已完成、验证并归档。
- sap-nexus-agent-llm-intent-adapter 已完成、验证并归档。
- sap-nexus-agent-workbench-console 已完成、验证并归档。
- sap-nexus-workbench-live-agent-runtime 已完成、验证并归档。
- sap-nexus-inventory-md04-stock-req-list 已完成、验证并归档。
- sap-nexus-registry-ontology-contract 已完成、验证并归档。
- 主 specs 已生成：capability-registry-gateway、agent-callplan-evidence、agent-workbench-console、registry-ontology-contract。
- Registry contract validator、executor binding schema、OWL skeleton、eval linkage 和 registry contract tests 已落地。
- 当前无 active OpenSpec change。
- 不要重复实现 Gateway / Registry execution baseline / JCo connectivity / Python Agent CallPlan / LLM intent adapter / Workbench Console / Registry OWL contract。

今天目标：
启动并推进 OpenSpec / Comet change：sap-nexus-gateway-execution-contract。

目标链路：
Capability Registry YAML
-> executorBinding.bindingId
-> TechnicalExecutionRequest
-> bindingId dispatcher
-> JCO_RFC adapter compatibility
-> TechnicalExecutionResult
-> current ExecutionResult compatibility
-> TraceSpan / redaction consistency
-> Agent / ReasoningFact unchanged
-> OpenSpec / traceable verification evidence

范围约束：
- 只定义并落地 Gateway technical execution contract、binding dispatcher contract、当前 JCO_RFC compatibility adapter、request-owned technical detail guards、technical result / redaction consistency。
- 不新增 SAP capability。
- 不实现 OData Gateway、CDS / ADT Gateway 或 REST JSON Gateway runtime。
- 不接入 STO 创建或其他 SAP write action。
- 不加入任意 HTTP 客户端、任意 URL 执行、任意 ADT SQL、任意 RFC 执行或 LLM 生成 JSON payload 执行。
- 不做 SAP Write Action、RecommendationPlan、ML uncertainty reasoning、UI、多域复杂编排。
- 不提交 .env、SAP 密码、destination config、token、LLM API key 或 runtime traces。

开始前请先执行并汇报：
- git status --short
- openspec list --json
- openspec validate --all --strict
- scripts/verify-agent-callplan-evidence.sh
- .venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
- .venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
```

---

## Session Closeout - 2026-06-28

### Completed

- Opened active Comet/OpenSpec change `sap-nexus-gateway-execution-contract`.
- Created Design Doc `docs/superpowers/specs/2026-06-28-gateway-execution-contract-design.md`.
- Created implementation plan `docs/superpowers/plans/2026-06-28-gateway-execution-contract.md`.
- Added Gateway-internal technical execution contract classes under `gateway-jco/src/main/java/com/sapnexus/gateway/execution/`.
- Added `TechnicalExecutionRequest`, `TechnicalExecutionResult`, closed `TechnicalExecutionDispatcher`, `TechnicalAdapter`, `JcoRfcTechnicalAdapter`, and `TechnicalRedactor`.
- Extended Java Registry model/loading with `CapabilityDefinition.ExecutorBinding` and `executorBinding.bindingId` parsing.
- Integrated capability execution through the technical dispatcher while preserving the existing public `/capabilities/{capabilityId}/execute` response shape.
- Added request ownership guard rejecting caller-owned technical override fields such as `rfcName`.
- Strengthened trace redaction by sharing the technical sensitive-key coverage.
- Archived OpenSpec / Comet change at `openspec/changes/archive/2026-06-28-sap-nexus-gateway-execution-contract/`.
- Merged final spec into `openspec/specs/gateway-execution-contract/spec.md`.

### Verified

- Command: `cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test --tests '*CapabilityExecutionApiTest' --tests '*CapabilityRegistryLoaderTest' --tests '*TechnicalExecutionDispatcherTest' --tests '*TechnicalRedactorTest'`
- Result: `BUILD SUCCESSFUL`
- Command: `cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test`
- Result: `BUILD SUCCESSFUL`
- Command: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
- Result: `Registry contract valid: registry/capabilities.yaml`
- Command: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`
- Result: `13 passed`
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: `54 passed, 1 skipped`; `Eval passed: 7/7`; OpenSpec validation inside script passed `5 passed, 0 failed`
- Command: `openspec validate --all --strict`
- Result: `5 passed, 0 failed`

OpenSpec printed PostHog telemetry DNS/network flush errors after valid validation output. These were treated as non-blocking because the commands exited successfully and the authoritative validation output passed.

### Blockers

- None for implementation.
- Workflow note: user explicitly chose to implement directly on current branch `main` and requested the build isolation guard be ignored; Comet state records `isolation=branch` as the current-branch execution mode.

### Next Start Here

1. Start Runbook 08: `docs/runbooks/08-capability-matching-contract.md`.
2. Use archived Runbook 05 artifacts as the Gateway execution boundary for future executor pilots.
3. Keep `sap-nexus-gateway-execution-contract` closed unless a follow-up bugfix or contract tweak is opened explicitly.
