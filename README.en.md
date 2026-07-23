> **English** | [中文](README.md)

# SAP Nexus Agent

SAP Nexus Agent is a **capability-ontology-governed SAP access gateway**. It currently models SAP business capabilities and parameter constraints through a YAML Registry, JSON Schema, Fact Type / Capability Relation catalogs, and an immutable in-process semantic graph. The LLM Agent may propose intent or plan candidates only within registered capability boundaries. All data access must pass through the Capability Registry, deterministic validation, and allowlisted executor bindings. No bare RFC, OData, or SQL calls are permitted.

**Core principle: Capability is the boundary — this is a governed capability gateway, not a generic SAP proxy.**

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
│  · CallPlan generation                    │
│  · ReasoningFact construction             │
│  · Chinese / English narrative            │
└──────────────┬──────────────────────────┘
               │ capabilityId + parameters
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

### Governance & Security

- **Fail-closed** — Unsupported executor types (`CDS_ADT` / `REST_JSON` / `SQL_READ`) default to denial
- **Parameter injection protection** — Callers cannot supply or override `rfcName`, `bindingId`, service URLs, HTTP methods, credential references, raw SQL, CDS objects, etc.
- **READ safety** — READ capabilities must never call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`
- **WRITE human approval** — WRITE capabilities (e.g. purchase requisition creation) require explicit human approval before execution
- **Full-chain audit** — Every execution produces a TraceSpan recording the complete chain: intent → CallPlan → validation → execution → evidence → narrative

### Executor Families

| Type | Status | Description |
|------|--------|-------------|
| `JCO_RFC` | ✅ Live | Direct RFC/BAPI execution via SAP JCo |
| `ODATA` | ✅ Live | Thin reverse proxy → Python OData microservice → SAP OData |
| `CDS_ADT` | 🔒 Fail-closed | Architecture reserve |
| `REST_JSON` | 🔒 Fail-closed | Architecture reserve |
| `SQL_READ` | 🔒 Fail-closed | Architecture reserve |

### Current Runtime Maturity

- `FactType`, `CapabilityRelation`, `GoalSpec`, `PlanGraph`, and `RegistrySnapshot` contracts are implemented, verified, and archived; the product runtime still executes single-capability `CallPlan`s only.
- Workbench Runs and Gateway Approvals currently use process-local stores; restart recovery, long approvals, and multi-instance ownership are not production-ready.
- The current `/stream` route returns buffered SSE-formatted events after completion; it is not incremental or resumable streaming.
- Trusted principal, tenant, role, data scope, and ApprovalActor propagation are not integrated; WRITE remains sandbox/dev only.
- Shared S3, long approvals, multi-worker/HA, or non-sandbox WRITE require a separate trusted/durable runtime change first.

---

## Registered Capabilities

| Capability ID | Name | Executor | SAP Endpoint | Status |
|---------------|------|----------|--------------|--------|
| `MM.Inventory.GetAvailability` | Inventory Availability | `JCO_RFC` | `BAPI_MATERIAL_STOCK_REQ_LIST` | ✅ active |
| `MM.PurchaseOrder.GetList` | Purchase Order List | `ODATA` | `API_PURCHASEORDER_PROCESS_SRV` | ✅ active |
| `MM.PR.CreateDraft` | PR Create Draft | `JCO_RFC` | `BAPI_PR_CREATE` | ✅ active (requires approval) |

---

## Repository Layout

```text
agent/                   Python Agent package, tests, and evals
frontend/                Next.js Agent Workbench
services/
  gateway/               Java Spring Boot SAP Gateway (multi-module)
  odata-service/         Python OData read-only microservice
registry/                Capability registry and executor binding catalog
schemas/                 JSON Schema contracts
ontology/                Offline OWL identity skeleton
evals/                   Agent eval cases
scripts/                 Verification and registry validation helpers
docs/
  wiki/                  Architecture, roadmap, technology selection
  runbooks/              Session runbooks
openspec/                OpenSpec specs and archived changes
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

### Verification

```bash
scripts/comet-verify-gateway.sh
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

Expected: every command exits `0`. The current Agent baseline is `550 passed, 1 skipped`; evals are `7/7 + 13/13 + 9/9`; OpenSpec is `8 passed, 0 failed`. After moving the repository, reinstall the editable local package if it still points to the old checkout; `PYTHONPATH=agent` verifies the current source tree directly.

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
  "How much available stock does DEMOA1 have at 1000?" \
  --gateway-url http://127.0.0.1:8080 --intent-mode rule
```

Terminal 3 — Workbench:

```bash
SAP_NEXUS_AGENT_ROOT=$(pwd) \
SAP_NEXUS_GATEWAY_URL=http://127.0.0.1:8080 \
SAP_NEXUS_INTENT_MODE=rule \
npm --prefix frontend run dev
```

Open `http://127.0.0.1:3000/workbench`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent | Python package + OpenAI-compatible LLM + Rule hybrid |
| Gateway | Java 17 / Spring Boot / Gradle multi-module |
| SAP Connectivity | SAP JCo 3 (RFC) + SAP OData (HTTP) |
| Frontend | React / Next.js / TypeScript |
| Capability Registry | YAML + JSON Schema |
| Ontology | YAML + JSON Schema + immutable in-memory graph; offline OWL skeleton; graph database Reserved |
| Orchestration | OpenSpec / Comet lifecycle management |
| Runtime State | Local process Run/Approval state + JSONL traces; shared/production durable runtime requires a separate change |
| Authentication & Authorization | Not productized; shared environments require server-owned principal / tenant / role / data scope / ApprovalActor |

---

## Documentation

- [Technical Architecture](docs/wiki/sap-nexus-agent-technical-architecture.md)
- [Implementation Roadmap](docs/wiki/sap-nexus-agent-implementation-roadmap.md)
- [Technology Selection](docs/wiki/sap-nexus-agent-technology-selection.md)
- [OpenHarness Comparison](docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md)
- [DeerFlow Adoption Decision](docs/wiki/sap-nexus-agent-deerflow-adoption-analysis.md)
- [Execution Contract](openspec/specs/gateway-execution-contract/spec.md)
- [Runbooks](docs/runbooks/README.md)

---

## License

No open-source license file is currently included. Add an explicit `LICENSE` before publishing publicly.

---

## Quick Links

| | |
|---|---|
| AGENTS.md | Project-level agent behavioral rules |
| CLAUDE.md | Agent configuration |
| openspec/ | Specifications and change management |
| registry/ | Capability registry |
| ontology/ | OWL ontology skeleton |
| evals/ | Evaluation test cases |
