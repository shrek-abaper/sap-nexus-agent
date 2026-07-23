# Capability Registry Gateway Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `01-capability-registry-gateway` |
| Version | `v0.3.0` |
| Status | `Archived` |
| Created | `2026-06-18` |
| Updated | `2026-06-20` |
| Workstream | SAP Nexus Agent lifecycle architecture and first inventory read slice |
| Related Change | `sap-nexus-capability-registry-gateway` |
| Current Phase | Completed and archived |

---

## 1. Current Decision

The workstream has shifted from a narrow initial JCo connectivity kickoff to a product-level architecture baseline.

Important correction:

```text
JCo connectivity to SAP is already validated.
```

Therefore, the next implementation should not treat SAP/JCo connectivity as the primary unknown. The primary work is to wrap the validated JCo path into a governed SAP capability execution system:

```text
Capability Registry
-> CallPlan
-> Java JCo Gateway validate / execute
-> ExecutionResult
-> ReasoningFact
-> RecommendationPlan
-> Human Approval
-> SAP Action
-> Audit / Replay
```

---

## 2. Source Of Truth

Read these before implementation:

```text
AGENTS.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
docs/wiki/archive/sap-nexus-agent-mm-mvp-notion.md
```

The two primary lifecycle documents are now:

| Document | Role |
|---|---|
| `docs/wiki/sap-nexus-agent-technical-architecture.md` | Product architecture baseline from MVP to production |
| `docs/wiki/sap-nexus-agent-implementation-roadmap.md` | Lifecycle implementation roadmap from first Read Function to production governance |

---

## 3. Architecture Baseline

The product is not a simple LLM tool-calling wrapper. It is an SAP capability execution system governed by harnesses.

Core loop:

```text
User Intent
-> Intent Harness
-> Capability Selection
-> CallPlan
-> Validation
-> Java JCo Gateway
-> SAP BAPI/RFC
-> ExecutionResult
-> ReasoningFact
-> Deterministic / ML Reasoning
-> RecommendationPlan
-> Human Approval
-> SAP Write Action
-> Audit / Replay
```

MVP slice:

```text
Natural language inventory question
-> MM.Inventory.GetAvailability
-> BAPI_MATERIAL_AVAILABILITY
-> ExecutionResult
-> ReasoningFact
-> Narrative
-> AuditTrace
```

---

## 4. Current MVP Boundary

Do now:

- Use YAML/JSON as lightweight Capability Registry.
- Implement or scaffold capability-level Java JCo Gateway.
- Start with `MM.Inventory.GetAvailability`.
- Keep `ontologyIri` and `semanticType` fields for future OWL / Graph Registry migration.
- Generate `CallPlan`, `ExecutionResult`, `ReasoningFact`, and `TraceSpan`.

Do not do yet:

- No SAP write Action.
- No PR / PO creation.
- No GraphDB / Neo4j / Jena runtime dependency.
- No ML prediction execution.
- No arbitrary RFC endpoint.

---

## 5. First Implementation Change

Recommended first OpenSpec / Comet change:

```text
sap-nexus-capability-registry-gateway
```

Goal:

```text
Create a lightweight Capability Registry and Java JCo Gateway Harness that exposes only registered capability-level APIs.
```

Deliverables:

```text
registry/capabilities.yaml
gateway-jco/
schemas/execution-result.schema.json or equivalent model
runtime/traces/.gitignore
```

First capability:

```text
capabilityId: MM.Inventory.GetAvailability
kind: Function
executor.rfcName: BAPI_MATERIAL_AVAILABILITY
governance.sideEffect: none
governance.requiresApproval: false
```

---

## 6. Capability Registry Contract

The first Registry entry should include at least:

```yaml
capabilities:
  - capabilityId: MM.Inventory.GetAvailability
    ontologyIri: sapnexus:MM_Inventory_GetAvailability
    kind: Function
    domain: MM
    businessObject: InventoryStock
    intent: GetAvailability
    description: 查询指定物料在指定工厂的可用库存
    semanticVersion: 1.0.0
    status: active
    inputs:
      material:
        semanticType: Material
        sapField: MATERIAL
        required: true
        constraints:
          maxLength: 40
      plant:
        semanticType: Plant
        sapField: PLANT
        required: true
        constraints:
          maxLength: 4
      unit:
        semanticType: UnitOfMeasure
        sapField: UNIT
        required: false
        default: EA
    outputs:
      availableQuantity:
        semanticType: Quantity
        sapField: AV_QTY_PLT
        evidenceRole: primary_quantity
      unit:
        semanticType: UnitOfMeasure
        evidenceRole: quantity_unit
    executor:
      type: RFC
      rfcName: BAPI_MATERIAL_AVAILABILITY
    governance:
      sideEffect: none
      requiresApproval: false
      auditTags:
        - MM
        - INVENTORY_READ
```

Gateway must load this file instead of hardcoding capability behavior in controllers.

---

## 7. Gateway Rules

Required APIs:

```text
GET /health
GET /capabilities
POST /capabilities/{capabilityId}/validate
POST /capabilities/{capabilityId}/execute
```

Hard rules:

- Accept `capabilityId`, not arbitrary `rfcName`.
- Reject unknown capability with `CAPABILITY_NOT_FOUND`.
- Reject missing `material` or `plant` before SAP execution.
- Do not call commit / rollback for the Read Function.
- Do not log or return SAP passwords or sensitive destination config.
- Write trace for every execute.

---

## 8. Verification Commands

Before implementation:

```bash
git status --short
openspec list --json
```

After document updates:

```bash
rg -n "v0\.2\.0|Product Architecture Baseline|Lifecycle Roadmap|JCo 打通 SAP 已验证|Capability Registry|ReasoningFact|RecommendationPlan|Human Approval|OWL" docs/wiki docs/runbooks
```

After Gateway implementation exists:

```bash
curl -s http://localhost:<port>/health
curl -s http://localhost:<port>/capabilities
```

After Agent implementation exists:

```bash
python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
```

---

## 9. Safety Rules

Never commit:

```text
.env
SAP passwords
real SAP connection strings
sapjco native binaries unless explicitly approved
runtime traces containing sensitive data
```

Do not create a branch or worktree unless the user explicitly asks.

Do not commit unless the user explicitly asks.

---

## 10. Next Action

Open or implement the first change:

```text
sap-nexus-capability-registry-gateway
```

Use the lifecycle architecture and roadmap as the source of truth, not the older three-day JCo connectivity plan.

## 11. 2026-06-19 Gateway Implementation Checkpoint

Current OpenSpec change:

```text
sap-nexus-capability-registry-gateway
```

Implemented in the current branch:

- `registry/capabilities.yaml` as the lightweight runtime capability ontology.
- `schemas/capability.schema.json` and `schemas/execution-result.schema.json` as cross-language contracts.
- `gateway-jco/` Spring Boot 3.x + Java 17 Gateway skeleton.
- Official SAP JCo library layout copied from the validated `sap-sto-create` reference:
  - `gateway-jco/lib/sapjco3.jar`
  - `gateway-jco/lib/linux/libsapjco3.so`
  - `gateway-jco/lib/windows/sapjco3.dll`
- Gateway APIs:
  - `GET /health`
  - `GET /capabilities`
  - `POST /capabilities/{capabilityId}/validate`
  - `POST /capabilities/{capabilityId}/execute`
- Validation before execute for unknown, disabled, missing parameter, and invalid parameter cases.
- Real JCo execute path for `MM.Inventory.GetAvailability -> BAPI_MATERIAL_AVAILABILITY`.
- JSONL trace emission under ignored `runtime/gateway-jco/traces.jsonl`.
- Root `.env.example` for Gateway JCo variables; real `.env` is local-only and ignored.

Verified fast commands:

```bash
python3 -m json.tool schemas/capability.schema.json >/tmp/capability.schema.check.json
python3 -m json.tool schemas/execution-result.schema.json >/tmp/execution-result.schema.check.json
cd gateway-jco
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 GRADLE_USER_HOME=/tmp/gradle-home /tmp/gradle-8.8/bin/gradle --no-daemon test
```

Verified live smoke with local `.env`:

```text
GET /health -> jcoConfigured=true, sapEnvironmentPresent=true, sensitiveFieldsExposed=false
GET /capabilities -> returns MM.Inventory.GetAvailability
POST /validate -> success=true, errorType=NONE
POST /execute -> SAP JCo call reached BAPI_MATERIAL_AVAILABILITY and returned a normalized read result
```

Observed live execute sample:

```text
material=MAT-001, plant=1000, unit=EA
success=true
returnMessages includes SAP warning: Material MAT-001 not maintained in plant 1000
data.availableQuantity=0.000
errorType=NONE
```

Important local notes:

- The real `.env` must be shell-safe because SAP credentials may contain special characters. Use quoted `KEY='value'` form.
- Do not reintroduce `SAP_URL`; this Gateway uses SAP JCo destination variables, not SAP HTTP URL configuration.
- Codex sandbox blocks Gradle daemon socket creation; run Gradle with approved escalation or outside sandbox.
- Current Comet `.comet.yaml` still has `isolation: null` because the user explicitly chose current-branch development, while Comet only accepts `branch` or `worktree`.


### Code Review Follow-up

A subagent code review found four important issues before Comet verify. Fixes applied and re-verified:

- Trace redaction now recursively drops unsafe keys such as `password`, `passwd`, `token`, `secret`, `SAP_*`, `rfcName`, `destination`, `config`, and `env`.
- `/health` now uses the same `JcoDestinationProperties` readiness rules as the execute path, including required `SAP_LANG`.
- JCo failure `ExecutionResult` now keeps executor metadata so failure responses still match the schema.
- First capability output contract is unified to scalar `data.availableQuantity`, mapped from SAP export `AV_QTY_PLT`.
- Runtime registry validation now requires `executor.type`, `executor.rfcName`, `executor.inputMapping`, and `executor.outputMapping`.

Re-verified after fixes:

```text
Fast tests -> BUILD SUCCESSFUL
Live /health -> jcoConfigured=true, sapEnvironmentPresent=true, sensitiveFieldsExposed=false
Live /execute -> success=true, executor.rfcName=BAPI_MATERIAL_AVAILABILITY, data.availableQuantity=0.000
Latest trace parameterSummary -> material, plant, unit only; injected rfcName/destination were not written
```

---

## 12. 2026-06-19 Session Closeout - Completed And Archived

Final status for today's work:

```text
sap-nexus-capability-registry-gateway -> completed, verified, merged to main, archived
```

Completion evidence:

- Current branch after merge: `main`.
- Feature branch was locally merged and deleted after ancestry verification.
- OpenSpec / Comet archive exists at `openspec/changes/archive/2026-06-19-sap-nexus-capability-registry-gateway/`.
- Archived `.comet.yaml` has `verify_result: pass`, `branch_status: handled`, and `archived: true`.
- Main spec exists at `openspec/specs/capability-registry-gateway/spec.md`.
- Verification report is tracked at `docs/superpowers/reports/2026-06-19-sap-nexus-capability-registry-gateway-verify.md`.
- Implementation roadmap was updated to `v0.2.1` and now marks the Gateway change as completed and archived.

Final verification:

```bash
openspec validate --all --strict
```

Result:

```text
spec/capability-registry-gateway -> passed
Totals: 1 passed, 0 failed
```

Non-blocking note:

- OpenSpec may print PostHog telemetry network errors after valid JSON or validation output. Treat those as non-blocking when the command result itself succeeds.

### Do Not Repeat Tomorrow

Do not reopen or re-implement `sap-nexus-capability-registry-gateway` unless the user explicitly asks for a follow-up change. It is already complete and archived.

Do not treat JCo connectivity as the next risk. The live Gateway smoke already reached `BAPI_MATERIAL_AVAILABILITY` and returned normalized `ExecutionResult` data.

### Next Start Here

Recommended next workstream:

```text
sap-nexus-agent-callplan-evidence
```

Start from:

1. Read `docs/wiki/sap-nexus-agent-implementation-roadmap.md` `v0.2.1`.
2. Read `openspec/specs/capability-registry-gateway/spec.md` as the active Gateway behavior contract.
3. Open a new OpenSpec / Comet change for Python Agent CallPlan + Evidence.
4. Build only the read-only Agent path first: intent parse -> closed-set capability selection -> CallPlan -> Gateway validate / execute -> ReasoningFact -> Chinese narrator -> eval.
5. Keep SAP Write Action, RecommendationPlan, ML uncertainty reasoning, Knowledge Graph runtime, and UI out of the next change.
