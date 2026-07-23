# Agent CallPlan Evidence Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `02-agent-callplan-evidence` |
| Version | `v1.0.0` |
| Status | `Archived` |
| Created | `2026-06-20` |
| Updated | `2026-06-20` |
| Workstream | Python Agent read-only CallPlan and Evidence vertical slice |
| Related Change | `sap-nexus-agent-callplan-evidence` |
| Current Phase | Completed and archived |

---

## 1. Session Goal

This workstream starts from the completed Gateway baseline and moves into the Python Agent read-only vertical slice.

Recommended OpenSpec / Comet change:

```text
sap-nexus-agent-callplan-evidence
```

Target product path:

```text
Chinese user intent
-> Intent Harness
-> closed-set Capability Selection
-> CallPlan
-> Java Gateway validate / execute
-> ExecutionResult
-> ReasoningFact
-> Chinese Narrator
-> Eval / Trace evidence
```

Do not repeat the completed Gateway / Registry implementation unless the user explicitly asks for a follow-up hardening change.

---

## 2. Current Baseline

Completed and archived on `2026-06-19`:

```text
sap-nexus-capability-registry-gateway -> completed, verified, merged to main, archived
```

Evidence locations:

```text
openspec/changes/archive/2026-06-19-sap-nexus-capability-registry-gateway/
openspec/specs/capability-registry-gateway/spec.md
docs/superpowers/reports/2026-06-19-sap-nexus-capability-registry-gateway-verify.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
```

Implemented Gateway capabilities:

- `registry/capabilities.yaml` contains active `MM.Inventory.GetAvailability`.
- `gateway-jco/` provides Spring Boot Java 17 JCo Gateway.
- Gateway APIs are available by capability ID only:
  - `GET /health`
  - `GET /capabilities`
  - `POST /capabilities/{capabilityId}/validate`
  - `POST /capabilities/{capabilityId}/execute`
- Gateway maps `MM.Inventory.GetAvailability` to `BAPI_MATERIAL_AVAILABILITY`.
- Gateway returns normalized `ExecutionResult` and JSONL trace records.
- `.env.example` is present; real `.env` is local-only and ignored.

Verified live smoke from the Gateway baseline workstream:

```text
GET /health -> jcoConfigured=true, sapEnvironmentPresent=true, sensitiveFieldsExposed=false
GET /capabilities -> returns MM.Inventory.GetAvailability
POST /validate -> success=true, errorType=NONE
POST /execute -> success=true, executor.rfcName=BAPI_MATERIAL_AVAILABILITY, data.availableQuantity=0.000
Latest trace parameterSummary -> material, plant, unit only
```

---

## 3. Start Checklist

Run these before changing code:

```bash
git status --short
openspec list --json
openspec validate --all --strict
```

Read these source-of-truth docs:

```text
AGENTS.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
openspec/specs/capability-registry-gateway/spec.md
docs/runbooks/01-capability-registry-gateway.md
```

Expected state:

- Current branch is expected to be `main` unless the user changed it.
- Existing uncommitted documentation updates from session closeout may be present if not committed.
- OpenSpec may print PostHog telemetry network errors after valid output; treat them as non-blocking if the command itself succeeds.

---

## 4. Proposed Workstream Scope

Build only the read-only Python Agent path.

In scope:

- Python package or module skeleton for `sap_nexus_agent`.
- CLI entrypoint for a read-only inventory query.
- Intent Harness for Chinese inventory availability queries.
- Required parameter extraction for `material`, `plant`, optional `unit`.
- Missing-parameter clarification without calling Gateway.
- Closed-set capability selection from Registry; no free-form RFC generation.
- CallPlan creation before Gateway execution.
- Gateway client for validate / execute.
- `ExecutionResult` parsing.
- `ReasoningFact` creation from Gateway result.
- Chinese narrator that only cites facts present in `ReasoningFact`.
- Eval cases for happy path, missing params, invalid params, unknown intent, Gateway failure, and sensitive-data guard.

Out of scope:

- SAP Write Action.
- RecommendationPlan.
- ML uncertainty reasoning.
- Knowledge Graph runtime.
- UI.
- Multi-domain orchestration.

---

## 5. Suggested Artifact Shape

Prefer durable engineering artifacts over prompt-only behavior.

Potential directories:

```text
agent/
  sap_nexus_agent/
    cli.py
    intent.py
    capability_selector.py
    callplan.py
    gateway_client.py
    execution_result.py
    reasoning_fact.py
    narrator.py
    eval_runner.py
  tests/

evals/
  inventory_availability_cases.yaml

schemas/
  callplan.schema.json
  reasoning-fact.schema.json
```

Keep generated runtime artifacts ignored under `runtime/`.

---

## 6. Acceptance Criteria

Minimum acceptance:

| Area | Acceptance |
|---|---|
| Intent | Chinese inventory availability query maps to `MM.Inventory.GetAvailability` |
| Missing params | Missing `material` or `plant` returns clarification and does not call Gateway |
| Closed set | Unknown intent or capability is rejected before Gateway execution |
| CallPlan | Every executable request creates a structured CallPlan before validate / execute |
| Gateway client | Agent can call Gateway validate / execute when Gateway is running |
| Facts | `ExecutionResult` converts into `ReasoningFact` with trace/evidence fields |
| Narrator | Chinese answer only uses fields present in facts |
| Eval | Regression cases cover happy path, missing params, invalid params, unknown intent, Gateway failure, and sensitive-data guard |
| Safety | No `.env`, SAP password, destination config, or token is printed or committed |

Recommended fast verification command shape after implementation:

```bash
python -m pytest agent/tests
python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
openspec validate --all --strict
```

If a live Gateway smoke is needed, start `gateway-jco` with local `.env` and SAP JCo native library path, then run the Agent against `http://localhost:8080`.

---

## 7. Safety And Workflow Notes

- Do not commit `.env` or real SAP credentials.
- Do not print SAP passwords or full destination configuration.
- Do not add arbitrary RFC execution to the Agent or Gateway.
- Do not let LLM output create or override `rfcName`.
- Do not execute SAP write operations.
- Do not create or switch branches unless the user explicitly asks.
- If Comet workflow requires branch isolation, stop and ask the user before switching.
- Codex sandbox may block Gradle daemon socket creation; use approved escalation or outside-sandbox execution for Gateway tests.

---

## 8. Recommended First Steps Tomorrow

1. Confirm whether today's uncommitted documentation updates should be committed first.
2. Open a new OpenSpec / Comet change named `sap-nexus-agent-callplan-evidence`.
3. Design the Agent contracts around CallPlan and ReasoningFact before writing code.
4. Implement the smallest read-only Agent vertical slice with tests.
5. Run evals and record results before marking the change ready for verify.

---

## 9. Prompt To Start The Next Session

Copy and paste this prompt into a new session to continue work:

```text
继续 sap-nexus-agent 项目工作。

请先读取并遵守：
1. AGENTS.md
2. docs/runbooks/README.md
3. docs/runbooks/02-agent-callplan-evidence.md
4. docs/wiki/sap-nexus-agent-implementation-roadmap.md
5. openspec/specs/capability-registry-gateway/spec.md

当前状态：
- sap-nexus-capability-registry-gateway 已完成、验证、合并到 main 并归档。
- 主 spec 已生成：openspec/specs/capability-registry-gateway/spec.md。
- 不要重复实现 Gateway / Registry / JCo connectivity。
- JCo 打通 SAP 不是当前风险，当前重点是 Python Agent 的 read-only 库存查询纵切。

今天目标：
启动并推进 OpenSpec / Comet change：sap-nexus-agent-callplan-evidence。

目标链路：
Chinese user intent
-> Intent Harness
-> closed-set Capability Selection
-> CallPlan
-> Java Gateway validate / execute
-> ExecutionResult
-> ReasoningFact
-> Chinese Narrator
-> Eval / Trace evidence

范围约束：
- 只做 read-only Agent MVP。
- 只从 Registry 闭集选择 MM.Inventory.GetAvailability。
- 缺 material 或 plant 时必须澄清，不调用 Gateway。
- 不允许 LLM 生成或覆盖 rfcName。
- 不做 SAP Write Action、RecommendationPlan、ML uncertainty reasoning、Knowledge Graph runtime、UI、多域复杂编排。
- 不提交 .env、SAP 密码、destination config、token 或 runtime traces。

开始前请先执行并汇报：
- git status --short
- openspec list --json
- openspec validate --all --strict

如果发现昨天的 runbook / roadmap 文档变更还未提交，请先提醒我确认是否保留或提交，不要覆盖它们。
```
