> **English** | [中文](README.md)

# SAP Nexus Agent

SAP Nexus Agent's long-term goal is to build a capability intelligence hub for SAP On-Prem systems, not a single-purpose stock-lookup bot. This Harness Engineering-based governed access gateway ensures the Agent never directly touches bare RFC/OData/SQL endpoints—it may only propose intents or plan candidates through registered `capabilityId`s. All data access must pass through the Capability Registry, deterministic validation, and allowlisted executor bindings.

**Core principle: Facts before narrative; capability is the boundary — this is a governed capability gateway, not a generic SAP proxy.**

---

## Architecture Overview

```text
User Query (natural language)
  │
  ▼
┌─────────────────────────────────────────┐
│  Python Agent Layer                      │
│  · Semantic intent parsing (LLM + Rule)  │
│  · Registered capability selection        │
│  · CallPlan / PlanGraph v2 authoring      │
│  · ReasoningFact construction             │
│  · Chinese / English narrative            │
└──────────────┬──────────────────────────┘
               │ capabilityId + parameters
               ▼
┌─────────────────────────────────────────┐
│  TypeScript Composition Runtime         │
│  · PlanExecutor + durable node ledger   │
│  · Projection, Recommendation, Narrative│
│  · Workbench replay + governed Action   │
└──────────────┬──────────────────────────┘
               │ registered capabilityId only
               ▼
┌─────────────────────────────────────────┐
│  Java Gateway Execution Layer             │
│  · Parameter validation (ontology scope) │
│  · Executor routing (JCO_RFC / ODATA)    │
│  · Result normalization → TechnicalExecResult │
│  · Redaction / audit                     │
└────┬──────────────┬─────────────────────┘
     │              │
     ▼              ▼
  ┌────────┐  ┌──────────────┐
  │ JCo    │  │ OData Proxy   │
  │ (RFC)  │  │ (HTTP → SAP)  │
  └────────┘  └──────────────┘
     │              │
     └──────┬───────┘
            ▼
        SAP On-Prem System
```

---

## Key Features

### Capability Ontology Modeling (Core Differentiator)

- **Capability Ontology** — Every SAP operation (read/write) is modeled as a formal capability with `ontologyIri`, `semanticType`, typed inputs/outputs, and fact type references
- **Semantic Parameter Mapping** — Input parameters link to ontology concepts (`MaterialNumber`, `Plant`) via `semanticName`/`semanticType`, decoupled from SAP technical parameters (`MATERIAL`, `PLANT`)
- **Executor Binding** — Each capability binds to a specific executor (`JCO_RFC` / `ODATA`) via an allowlisted `bindingId`; runtime replacement is rejected
- **OWL Reserved** — `ontologyIri` and `semanticType` preserve a migration path for future OWL ontology reasoning; current consistency gates use JSON Schema + Registry Validator
- **Declarative Intent Parsing** — Rule-mode intent parsing is fully declaration-driven (`registry/capabilities.yaml` `intent` blocks + `registry/semantic-types.yaml` type catalog); adding a new capability requires no Agent code changes. Task 19's declaration-only capability proof verified the extension contract.

### Governance & Security

- **Fail-closed** — Unsupported executor types (`CDS_ADT` / `REST_JSON` / `SQL_READ`) default to denial
- **Parameter injection protection** — Callers cannot supply or override `rfcName`, `bindingId`, service URLs, HTTP methods, credential references, raw SQL, CDS objects, etc.
- **READ safety** — READ capabilities must never call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`
- **WRITE human approval** — WRITE capabilities (e.g. purchase requisition creation) require explicit human approval before execution
- **Full-chain audit** — Every execution produces a TraceSpan recording the complete chain: intent → CallPlan → validation → execution → evidence → narrative

### Executor Families

| Type        | Status        | Description                                                |
| ----------- | ------------- | ---------------------------------------------------------- |
| `JCO_RFC`   | ✅ Live        | Direct RFC/BAPI execution via SAP JCo                      |
| `ODATA`     | ✅ Live        | Thin reverse proxy → Python OData microservice → SAP OData |
| `CDS_ADT`   | 🔒 Fail-closed | Architecture reserve                                       |
| `REST_JSON` | 🔒 Fail-closed | Architecture reserve                                       |
| `SQL_READ`  | 🔒 Fail-closed | Architecture reserve                                       |

### Current Runtime Maturity

- **Offline end-to-end governed composition is implemented and working**: intent → CallPlan → validation/execution → ExecutionResult → ReasoningFact → narrative → durable Workbench replay → plan-aware single Action continuation. The single-capability `CallPlan` main chain remains available.
- **Python Agent responsibilities**: LLM-first intent, closed-set recall, five-state decisioning, and PlanGraph v2 authoring.
- **TypeScript composition coordinator**: Wires up PlanExecutor, OutputProjection, Recommendation, grounded Narrative, durable Workbench replay, and plan-aware single-Action continuation.
- **Release gate milestone**: The offline L1/L2/L3 gate reached `22/22` on 2026-08-19, with the highest consecutive level `L3_ACTION_GOVERNED`; headline hard gates are leakage `0`, approval bypass `0`, unsupported claim `0`, lineage `100%`. The earlier 2026-08-10 `22/22` report was produced from a code state that never entered commit history (its codeVersion is absent from git); it cannot be reproduced from committed state and is not a current-status reference.
- **Current architectural limits (design choices, not defects)**:
  - Run/Session, principal ownership, approval, lease/idempotency, and cursor SSE are already durable; but the current local JSONL/file store and placeholder principal are still not a shared multi-worker/HA store or a production identity system
  - Knowledge/RAG, free-form Tool Calling, a general Dynamic Planner, multi-WRITE/Saga, and automatic compensation remain Reserved / Not In Scope
  - Graph databases and OWL reasoning runtime are reserved directions; JSON Schema + Registry Validator currently carry consistency duties
- **SAP connectivity**: All three registered capabilities (two READs + one WRITE) have been verified end-to-end against a real SAP system via live smoke tests (execution records in `runtime/gateway-jco/traces.jsonl`); the `liveSmoke` field in the offline release-gate report stays `not_run` by design (the offline gate never calls a real SAP system; live verification runs separately); any live WRITE still requires exact-subject Human Approval.

---

## Registered Capabilities

| Capability ID                  | Name                           | Executor  | SAP Endpoint                    | Status                       |
| ------------------------------ | ------------------------------ | --------- | ------------------------------- | ---------------------------- |
| `MM.Inventory.GetAvailability` | Stock/Requirements List (MD04) | `JCO_RFC` | `BAPI_MATERIAL_STOCK_REQ_LIST`  | ✅ active                     |
| `MM.PurchaseOrder.GetList`     | Purchase Order List            | `ODATA`   | `API_PURCHASEORDER_PROCESS_SRV` | ✅ active                     |
| `MM.Material.GetInfo`          | Material Info (base UoM / purchasing group) | `JCO_RFC` | `BAPI_MATERIAL_GET_DETAIL` | ✅ active            |
| `MM.PR.CreateDraft`            | PR Create Draft                | `JCO_RFC` | `BAPI_PR_CREATE`                | ✅ active (requires approval) |
| `SD.SalesOrder.GetList`        | Sales Order List (VA05-style)  | `JCO_RFC` | `BAPI_SALESORDER_GETLIST`       | ✅ active                     |
| `FI.AR.GetOpenItems`           | Customer Open Items            | `JCO_RFC` | `BAPI_AR_ACC_GETOPENITEMS`      | ✅ active                     |
| `FI.AP.GetOpenItems`           | Vendor Open Items              | `JCO_RFC` | `BAPI_AP_ACC_GETOPENITEMS`      | ✅ active                     |

7 capabilities: 6 read-only (`kind: Function`, `sideEffect: none`) plus one write
(`MM.PR.CreateDraft`), which cannot execute without a recorded human confirmation.

---

## Repository Layout

```text
agent/                   Python Agent package, tests, and evals
frontend/                Next.js Agent Workbench + TypeScript Composition Runtime (src/runtime)
services/
  gateway/               Java Spring Boot SAP Gateway (multi-module)
  odata-service/         Python OData read-only microservice
registry/                Capability registry and executor binding catalog
schemas/                 JSON Schema contracts
ontology/                Offline OWL identity skeleton
runtime/                 Runtime traces, dev-services, gateway-jco, and release-gate eval results
evals/                   Agent eval cases
scripts/                 Verification and registry validation helpers
docs/
  wiki/                  Architecture, roadmap, technology selection
  runbooks/              Session runbooks
```

---

## Quick Start

### Prerequisites

- Java 17
- Gradle 8.8+ (or use `services/gateway/gradlew`)
- Python 3.12+
- Node.js 20+
- SAP JCo 3 library files (for live SAP execution)
- SAP On-Prem connectivity and credentials (for live smoke tests)

Fast tests do not require SAP connectivity or credentials.

### Environment Setup

```bash
cp .env.example .env
# Fill in SAP connection parameters, LLM API Key, etc.
```

### Verification (as of 2026-08-19)

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
npm --prefix frontend run verify
npm --prefix frontend run release-gate -- --profile all
```

Current baselines:
- Agent test suite: `1288 passed, 0 failed, 1 skipped`
- Frontend test suite: `524 passed, 0 failed`
- Call-plan Eval: `inventory 7/7` ✅, `eval_harness_seed_cases.json 13/13` ✅, `PR 9/9` ✅, `matcher_cases.yaml 23/23` ✅, `dry-run 3/3` ✅
- Offline release gate: Reached `22/22` / `L3_ACTION_GOVERNED` on 2026-08-19

`PYTHONPATH=agent` verifies the current source tree directly.

### Launch Services

Terminal 1 — Gateway:

```bash
set -a; . ./.env; set +a
cd services/gateway
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
  /tmp/gradle-8.8/bin/gradle --no-daemon bootRun
```

Terminal 2 — OData microservice (required for PO capability):

```bash
cd services/odata-service
PYTHONPATH=. python -m odata_service.server
```

Terminal 3 — Agent CLI:

```bash
PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.cli \
  "How much available stock does A100 have at 1000?" \
  --gateway-url http://127.0.0.1:8080 --intent-mode rule
```

Terminal 3 — Workbench:

```bash
set -a; . ./.env; set +a
SAP_NEXUS_AGENT_ROOT=$(pwd) \
SAP_NEXUS_GATEWAY_URL=http://127.0.0.1:8080 \
SAP_NEXUS_INTENT_MODE=rule \
npm --prefix frontend run dev
```

Open `http://127.0.0.1:3000/workbench`.

---

## Tech Stack

| Layer                          | Technology                                                                                                                                                    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent                          | Python package + OpenAI-compatible LLM + Rule hybrid                                                                                                          |
| Gateway                        | Java 17 / Spring Boot / Gradle multi-module                                                                                                                   |
| SAP Connectivity               | SAP JCo 3 (RFC) + SAP OData (HTTP)                                                                                                                            |
| Frontend                       | React / Next.js / TypeScript                                                                                                                                  |
| Capability Registry            | YAML + JSON Schema                                                                                                                                            |
| Ontology                       | YAML + JSON Schema + immutable in-memory graph; offline OWL skeleton; graph database Reserved                                                                 |
| Runtime State                  | Local JSONL/file-backed Run/Session/Approval + JSONL traces; not a shared multi-worker/HA store; shared/production durable runtime requires a separate change |
| Authentication & Authorization | Not productized; shared environments require server-owned principal / tenant / role / data scope / ApprovalActor                                              |

---

## Documentation

- [Technical Architecture](docs/wiki/sap-nexus-agent-technical-architecture.md)
- [Implementation Roadmap](docs/wiki/sap-nexus-agent-implementation-roadmap.md)
- [Technology Selection](docs/wiki/sap-nexus-agent-technology-selection.md)

---

## License

This project is licensed under [Apache-2.0](LICENSE).

---

## Quick Links

|           |                                      |
| --------- | ------------------------------------ |
| AGENTS.md | Project-level agent behavioral rules |
| CLAUDE.md | Agent configuration                  |
| registry/ | Capability registry                  |
| ontology/ | OWL ontology skeleton                |
| evals/    | Evaluation test cases                |