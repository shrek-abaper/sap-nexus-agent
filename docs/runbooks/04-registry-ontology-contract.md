# Registry Ontology Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `04-registry-ontology-contract` |
| Version | `v0.6.1` |
| Status | `Archived` |
| Created | `2026-06-20` |
| Updated | `2026-06-25` |
| Workstream | Registry schema, OWL skeleton, multi-executor binding contract including `REST_JSON`, capability contract validation, and eval linkage |
| Related Change | `sap-nexus-registry-ontology-contract` |
| Current Phase | Archived |

---

## 1. Session Goal

Start the Registry / OWL contract hardening change after the Agent Workbench Console workstream:

```text
sap-nexus-registry-ontology-contract
```

Target product path:

```text
Capability Registry YAML
-> Semantic capability / technical binding split
-> Registry JSON Schema
-> Capability Contract Validator
-> OWL skeleton identity
-> Governance consistency checks
-> Eval linkage
-> Multi-executor binding readiness
-> REST_JSON contract readiness for SAP-context external system facts
-> OpenSpec / traceable verification evidence
```

Do not repeat Gateway / Registry execution or Python Agent CallPlan implementation unless the user explicitly asks for follow-up hardening.

---

## 2. Expected Baseline Before Starting This Workstream

This runbook is intended for use after the Agent Workbench Console workstream is completed. Expected completed and archived changes:

```text
sap-nexus-capability-registry-gateway -> completed, verified, archived
sap-nexus-agent-callplan-evidence -> completed, verified, archived
sap-nexus-agent-llm-intent-adapter -> completed, verified, archived
sap-nexus-agent-workbench-console -> completed, verified, archived
sap-nexus-workbench-live-agent-runtime -> completed, verified, archived
sap-nexus-inventory-md04-stock-req-list -> completed, verified, archived
```

Main specs:

```text
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/agent-callplan-evidence/spec.md
openspec/specs/agent-workbench-console/spec.md
openspec/specs/registry-ontology-contract/spec.md
```

Key implemented artifacts:

- `registry/capabilities.yaml` contains active `MM.Inventory.GetAvailability`.
- `gateway-jco/` exposes capability-ID-only validate / execute APIs.
- `agent/` implements the read-only Agent vertical slice:
  - Chinese intent parsing with `hybrid` intent mode by default
  - OpenAI-compatible LLM intent adapter with deterministic rule fallback
  - closed-set capability selection
  - CallPlan creation
  - Gateway validate / execute client
  - `ExecutionResult` parsing
  - `ReasoningFact` building
  - Chinese fact-only narration
  - eval runner
- `schemas/call-plan.schema.json` and `schemas/reasoning-fact.schema.json` are present.
- `evals/inventory_availability_cases.yaml` covers the Agent MVP regression set.
- `.env.example` contains placeholder-only `LLM_*` model gateway configuration.
- `frontend/` contains the internal Agent console baseline.
- `sap-nexus-workbench-live-agent-runtime` and `sap-nexus-inventory-md04-stock-req-list` are completed and archived.
- Current inventory technical path is `BAPI_MATERIAL_STOCK_REQ_LIST` through `JCO_RFC`.

Verified Agent CallPlan / Evidence + LLM intent adapter baseline:

```text
scripts/verify-agent-callplan-evidence.sh
-> 41 passed, 1 skipped
-> Eval passed: 7/7
-> openspec validate --all --strict: 3 passed, 0 failed
```

Optional live LLM smoke test:

```text
agent/tests/test_llm_live.py
-> skipped by default
-> passes only when SAP_NEXUS_LLM_LIVE=1 and local LLM_* environment variables are available
```

OpenSpec may print PostHog telemetry network errors after valid command output. Treat those as non-blocking if the command exits successfully and the OpenSpec validation result is passed.

---

## 3. Start Checklist

Run these before changing code:

```bash
git status --short
openspec list --json
openspec validate --all --strict
scripts/verify-agent-callplan-evidence.sh
```

Read these source-of-truth docs:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/04-registry-ontology-contract.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/agent-callplan-evidence/spec.md
openspec/specs/agent-workbench-console/spec.md
```

Expected state:

- Current branch is expected to be `main` unless the user changed it.
- `openspec list --json` should show no active changes before this workstream starts.
- `git status --short` should be clean or contain only user-confirmed local edits.
- The LLM adapter and Agent Workbench Console are expected to be part of the baseline; do not reopen those workstreams unless contract validation finds a concrete gap.

---

## 4. Proposed Workstream Scope

Build only the Registry / OWL contract hardening layer.

In scope:

- Registry JSON Schema for `registry/capabilities.yaml`.
- Multi-executor binding schema with `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` as known executor types.
- Semantic capability and technical binding split: capability owns business semantics; Gateway owns only protocol execution.
- Binding references for future OData Gateway, CDS / ADT Gateway, and REST JSON Gateway, without implementing those gateways.
- `REST_JSON` binding shape for SAP-context external system facts, including `systemRef`, fixed HTTP method, path template, JSON request/response mapping, credential reference, timeout, retry, and side-effect guard.
- Local validator command for schema and semantic consistency checks.
- Checks for stable `capabilityId`, `ontologyIri`, `kind`, executor mapping, side effects, approval policy, and eval linkage.
- OWL skeleton files under `ontology/` for core SAP Nexus concepts and MM inventory capability identity.
- Tests or evals proving `MM.Inventory.GetAvailability` passes the contract and intentionally invalid examples fail.
- Documentation of the validation command in the nearest README, runbook, or roadmap section.
- Architecture notes that OData technical patterns can reference `sap-sto-create`, and CDS / ADT technical patterns can reference `sap-adt-cli`.

Out of scope:

- Knowledge Graph runtime.
- Graph Registry backend.
- New SAP capability implementation.
- Java Gateway reimplementation.
- OData Gateway runtime implementation.
- CDS / ADT Gateway runtime implementation.
- REST JSON Gateway runtime implementation.
- STO creation or other OData write action.
- Arbitrary HTTP client behavior, arbitrary URL execution, or LLM-generated JSON payload execution.
- Arbitrary ADT SQL exposure.
- Python Agent behavior changes unless required by contract validation.
- SAP Write Action.
- RecommendationPlan.
- ML uncertainty reasoning.
- UI.

---

## 5. Suggested Artifact Shape

Prefer deterministic validators and versionable contracts:

```text
registry/
  capabilities.yaml
  capability.schema.json
  executor-binding.schema.json
  README.md

ontology/
  sapnexus-core.owl
  mm-inventory.owl
  README.md

scripts/
  validate-registry-contract.py

# Future, not in this workstream:
# gateway-odata/ or gateway/executors/odata/
# gateway-cds-adt/ or gateway/executors/cds-adt/
# gateway-rest-json/ or gateway/executors/rest-json/

tests/
  registry/
    test_registry_contract.py
```

If the existing project structure suggests a better local placement, keep the change surgical and document the chosen command.

---

## 6. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Schema | `registry/capabilities.yaml` passes a deterministic schema validator |
| Identity | `MM.Inventory.GetAvailability` maps to stable `sapnexus:MM_Inventory_GetAvailability` |
| Governance | `Function` capabilities cannot declare write side effects or require unapproved write execution |
| Executor | External callers still cannot provide or override `rfcName`, OData service URL, CDS view, ADT path, REST endpoint, HTTP method, JSON payload mapping, or `bindingId` |
| OWL skeleton | Core and MM inventory OWL files define stable classes / individuals for future migration |
| Eval linkage | Active capability has matching Agent / Gateway regression coverage |
| REST JSON readiness | `REST_JSON` binding shape is expressible and constrained as a read-only external fact source without implementing runtime execution |
| Safety | No `.env`, SAP password, destination config, token, or runtime trace is committed |

Recommended verification command shape after implementation:

```bash
python -m pytest tests/registry
python scripts/validate-registry-contract.py registry/capabilities.yaml
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

Adjust the exact commands to match the implemented file names.

---

## 7. Safety And Workflow Notes

- Do not create or switch branches unless the user explicitly asks.
- Do not commit `.env` or real SAP credentials.
- Do not print SAP passwords or full destination configuration.
- Do not add arbitrary RFC execution to the Agent or Gateway.
- Do not add arbitrary HTTP / REST execution to the Agent or Gateway.
- Do not let LLM output create or override `rfcName`.
- Do not let LLM output create or override REST URL, HTTP method, headers, token, or JSON payload.
- Do not commit real `LLM_API_KEY`, model gateway URL with secrets, or raw live LLM responses.
- Do not introduce Knowledge Graph runtime dependency in this change.
- Treat OWL as offline semantic contract scaffolding only.

---


## Session Closeout - 2026-06-24 Build In Progress

### Completed

- Opened `sap-nexus-registry-ontology-contract` through Comet / OpenSpec.
- Added OpenSpec proposal, design, tasks, and delta spec for `registry-ontology-contract`.
- Added technical Design Doc at `docs/superpowers/specs/2026-06-24-registry-ontology-contract-design.md`.
- Added implementation plan at `docs/superpowers/plans/2026-06-24-registry-ontology-contract.md`.
- Added initial Registry contract artifacts: `executorBinding`, eval linkage, `registry/executor-bindings.yaml`, `schemas/executor-binding.schema.json`, deterministic validator, registry tests, and OWL skeleton files.

### Verified So Far

- Command: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`
- Result: registry contract tests pass in the current build stage.
- Command: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
- Result: current Registry contract validates.
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: existing Agent / eval / OpenSpec regression passed after Task 1; PostHog flush errors remain non-blocking when exit code is 0.

### Blockers

- None for the current build path.

### Next Start Here

1. Continue `openspec/changes/sap-nexus-registry-ontology-contract/tasks.md` from the first unchecked item.
2. Re-run registry validator, registry tests, Agent regression, and OpenSpec strict validation before moving to Comet verify.
3. Do not implement OData / CDS / REST runtime, arbitrary HTTP client, Knowledge Graph runtime, SAP write Action, RecommendationPlan, ML reasoning, or UI.

---

## Session Closeout - 2026-06-25 Archived

### Completed

- Completed, verified, locally merged, and archived `sap-nexus-registry-ontology-contract`.
- Created main spec `openspec/specs/registry-ontology-contract/spec.md`.
- Archived OpenSpec change at `openspec/changes/archive/2026-06-24-sap-nexus-registry-ontology-contract/`.
- Added Registry / OWL contract artifacts:
  - `registry/executor-bindings.yaml`
  - `schemas/executor-binding.schema.json`
  - `scripts/validate-registry-contract.py`
  - `scripts/validate_registry_contract.py`
  - `ontology/sapnexus-core.owl`
  - `ontology/mm-inventory.owl`
  - `agent/tests/test_registry_contract.py`
- Preserved scope boundaries: no OData / CDS / REST runtime, no arbitrary HTTP client, no Knowledge Graph runtime, no new SAP capability, and no SAP write action.

### Verified

- Command: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
- Result: `Registry contract valid: registry/capabilities.yaml`
- Command: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`
- Result: `13 passed`
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: `54 passed, 1 skipped`; `Eval passed: 7/7`; OpenSpec passed.
- Command: `openspec list --json`
- Result: `{"changes":[]}`
- Command: `openspec validate --all --strict`
- Result: `4 passed, 0 failed`

OpenSpec PostHog telemetry may still print network flush errors in restricted-network environments; treat them as non-blocking when command exit code is 0 and validation output passes.

### Blockers

- None for this archived workstream.

### Next Start Here

1. Start a new OpenSpec / Comet change for `sap-nexus-gateway-execution-contract` if continuing the roadmap.
2. Use `openspec/specs/registry-ontology-contract/spec.md` as the source of truth for Registry / OWL contract requirements.
3. Do not reopen Gateway / Registry execution / JCo connectivity / Python Agent CallPlan / LLM intent adapter / Workbench Console unless a concrete regression is found.
4. Keep future OData / CDS / REST runtime pilots as separate changes.

---
## 8. Recommended First Steps

1. Confirm no active OpenSpec changes with `openspec list --json`.
2. Read `openspec/specs/registry-ontology-contract/spec.md` before modifying Registry, OWL, or executor binding contracts.
3. If continuing the roadmap, open `sap-nexus-gateway-execution-contract` as a separate change.
4. Keep future OData, CDS / ADT, and REST JSON gateway pilots separate from the Registry / OWL contract workstream.
5. Run registry validation, Agent regression, and OpenSpec strict validation before verify / archive.

---

## 9. Prompt To Start The Next Session

```text
继续 sap-nexus-agent 项目工作。

请先读取并遵守：
1. AGENTS.md
2. docs/runbooks/README.md
3. docs/runbooks/04-registry-ontology-contract.md
4. docs/wiki/sap-nexus-agent-implementation-roadmap.md
5. openspec/specs/capability-registry-gateway/spec.md
6. openspec/specs/agent-callplan-evidence/spec.md

当前状态：
- sap-nexus-capability-registry-gateway 已完成、验证并归档。
- sap-nexus-agent-callplan-evidence 已完成、验证并归档。
- sap-nexus-agent-llm-intent-adapter 已完成、验证并归档。
- sap-nexus-agent-workbench-console 已完成、验证并归档。
- sap-nexus-workbench-live-agent-runtime 已完成、验证并归档。
- sap-nexus-inventory-md04-stock-req-list 已完成、验证并归档。
- 主 specs 已生成：capability-registry-gateway、agent-callplan-evidence 和 agent-workbench-console。
- Agent 已支持 `hybrid` intent mode：真实 LLM 优先，规则解析兜底。
- Agent Workbench Console 已提供内部控制台基线。
- sap-nexus-registry-ontology-contract 已完成、验证并归档。
- 主 spec 已生成：registry-ontology-contract。
- Registry contract validator、executor binding schema、OWL skeleton、eval linkage 和 registry contract tests 已落地。
- 不要重复实现 Gateway / Registry execution / JCo connectivity / Python Agent CallPlan / LLM intent adapter / Workbench Console，也不要重复 open/design。

今天目标：
启动并推进下一个 OpenSpec / Comet change：sap-nexus-gateway-execution-contract。

目标链路：
Capability Registry YAML
-> Semantic capability / technical binding split
-> Registry JSON Schema
-> Capability Contract Validator
-> OWL skeleton identity
-> Governance consistency checks
-> Eval linkage
-> Multi-executor binding readiness
-> REST_JSON contract readiness for SAP-context external system facts
-> OpenSpec / traceable verification evidence

范围约束：
- 只做 Registry / OWL contract hardening 和 multi-executor binding schema 预留，包含 `REST_JSON` 契约预留。
- 不做 Knowledge Graph runtime 或 Graph Registry backend。
- 不新增 SAP capability。
- 不实现 OData Gateway、CDS / ADT Gateway 或 REST JSON Gateway runtime。
- 不接入 STO 创建或其他 SAP write action。
- 不加入任意 HTTP 客户端、任意 URL 执行或 LLM 生成 JSON payload 执行。
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
