> **English** | [中文](README.md)

# SAP Nexus Agent

SAP Nexus Agent's long-term goal is to build a **capability intelligence hub for SAP On-Prem systems — a supplier of SAP capabilities** — rather than a single-purpose stock-lookup bot. This Harness Engineering-based governed access gateway ensures the Agent never directly touches bare RFC/OData/SQL endpoints: it may only propose intents or plan candidates through registered `capabilityId`s. All data access must pass through the Capability Registry, deterministic validation, and allowlisted executor bindings. The harness (orchestration and presentation) is replaceable; semantic governance and SAP execution stay server-side.

**Core principle: Facts before narrative; capability is the boundary — this is a governed capability gateway, not a generic SAP proxy.**

---

## Target Architecture (Agent Build Target)

> The diagram below is this project's **target architecture (the Agent build target)**, **not the current state of this repository**; the as-is implementation follows in the next section. The diagram shows target form only — no progress, counts, or dates — and is updated only when layers, layer responsibilities, contract red lines, or derivation relations change. Implementation progress is tracked solely in [“Target Achievement Status”](#target-achievement-status-s1s5) below and in [roadmap §1.1](docs/wiki/sap-nexus-agent-implementation-roadmap.md). The reading guide: **definitions at the top, reasoning at compile time, governance inside capabilities, replaceable experience**. The stance is “four parties, one job each”: the capability ontology (single YAML source), the compile-time derivation pipeline (offline Capability Manifest), the SAP domain capability layer (business-semantic level, core asset), and the harness (replaceable orchestration and presentation).

![SAP Nexus Agent target architecture: an ontology-driven supplier of SAP capabilities](docs/images/nexus-target-architecture.png)

---

## Current Architecture (As-Is)

```text
Experience · Harness (replaceable)
  ┌──────────────────────────────┐  ┌──────────────────────────────────┐
  │ harness-dsh CLI (standalone   │  │ DSH Chat Workbench (/chat)       │
  │ Node package)                 │  │ browser + server-side in-process │
  │ dsh T-A-O loop · pinned rc.1  │  │ dsh runtime                      │
  └──────────────┬───────────────┘  └────────────────┬─────────────────┘
                 │ HTTP POST /api/semantic-tools      │ in-process call
                 └──────────────────┬─────────────────┘
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Next.js server (:3000)                                                │
  │ Semantic Tool Facade (contract v2 · shape validation · technical-key  │
  │   injection fail-closed)                                              │
  │ executeSemanticTool = single governed server entry (HTTP facade and    │
  │   dsh share it)                                                       │
  │ agent-runtime-adapter: spawns the Python Agent as a subprocess         │
  │ Composition Runtime: PlanExecutor · durable node ledger ·              │
  │   Projection · Recommendation · grounded Narrative · governed Action   │
  └────────────────────────────────┬────────────────────────────────────┘
                                   │ registered capabilityId only
                                   ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Java Gateway (:8080 · the only security boundary)                     │
  │ Parameter validation (ontology constraints) · executor routing        │
  │   (JCO_RFC / ODATA) · result normalization → TechnicalExecutionResult  │
  │ · redaction / audit                                                   │
  └──────────────────┬───────────────────────────────┬──────────────────┘
                     ▼                                ▼
           ┌──────────────────┐            ┌────────────────────────────┐
           │ SAP JCo (RFC/BAPI)│            │ odata-service (:8081)       │
           └────────┬─────────┘            │ Python read-only microsvc   │
                    │                      │ · assembles $filter         │
                    │                      └─────────────┬──────────────┘
                    └──────────────────┬─────────────────┘
                                       ▼
                              SAP On-Prem system

Side path: the Python Agent CLI (sap_nexus_agent.cli) can call the Gateway directly without a
harness (rule / llm intent); the classic Workbench at /workbench shares the same agent-runtime
+ composition governed chain as DSH Chat.
```

---

## Key Features

### Replaceable Harness (DSH Pilot)

- **Two harness forms**: the standalone `harness-dsh/` Node CLI (a dsh T-A-O loop calling the semantic-tool facade over HTTP) and the in-app **DSH Chat** (`/chat`, a server-side in-process dsh runtime with streamed reasoning traces, tool cards, and approval interaction); the root path `/` now 307-redirects to `/chat`
- **Business-semantic tool surface (Semantic Tool contract v2)**: the harness sees only 4 business tools (see table below) — never a `capabilityId`, `rfcName`, `bindingId`, URL, or credential; technical-key injection is rejected fail-closed at the facade
- **One governed server chain**: the HTTP facade and the in-process dsh handlers share `executeSemanticTool`; intent selection, CallPlan, validation, and approval all stay server-side. The harness process has no surface that reaches the Gateway / RFC / bindings / credentials directly (locked by `harness-dsh/tests/architecture.test.ts`)
- **Version pin**: `@deepseek-ai/dsh-*` packages are pinned exactly to `0.1.5-rc.1` and `@deepseek-ai/cordis` to `4.0.2`; while dsh is in preview, every upgrade is a separate reviewed change

### Capability Ontology Modeling (Core Differentiator)

- **Capability Ontology** — Every SAP operation (read/write) is modeled as a formal capability with `ontologyIri`, `semanticType`, typed inputs/outputs, and fact type references
- **Semantic Parameter Mapping** — Input parameters link to ontology concepts (`MaterialNumber`, `Plant`) via `semanticName`/`semanticType`, decoupled from SAP technical parameters (`MATERIAL`, `PLANT`)
- **Executor Binding** — Each capability binds to a specific executor (`JCO_RFC` / `ODATA`) via an allowlisted `bindingId`; runtime replacement is rejected
- **OWL Reserved** — `ontologyIri` and `semanticType` preserve a migration path for future OWL ontology reasoning; current consistency gates use JSON Schema + Registry Validator
- **Declarative Intent Parsing** — Rule-mode intent parsing is fully declaration-driven (`registry/capabilities.yaml` `intent` blocks + `registry/semantic-types.yaml` type catalog); adding a new capability requires no Agent code changes

### Governance & Security

- **Fail-closed** — Unsupported executor types (`CDS_ADT` / `REST_JSON` / `SQL_READ`) default to denial
- **Parameter injection protection** — Callers cannot supply or override `rfcName`, `bindingId`, service URLs, HTTP methods, credential references, raw SQL, or CDS objects; the semantic-tool facade scans for technical keys at any depth
- **READ safety** — READ capabilities must never call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`
- **WRITE human approval** — WRITE capabilities (purchase requisition creation / the `propose_replenishment` proposal) execute only when a recorded exact-subject human confirmation exists; the approval subject is computed and verified server-side
- **Full-chain audit** — Every execution produces a TraceSpan / JSONL trace recording intent → CallPlan → validation → execution → evidence → narrative

### Executor Families

| Type        | Status        | Description                                                                      |
| ----------- | ------------- | -------------------------------------------------------------------------------- |
| `JCO_RFC`   | ✅ Live        | Direct RFC/BAPI execution via SAP JCo                                            |
| `ODATA`     | ✅ Live        | Gateway thin reverse proxy → Python odata-service (:8081) → SAP OData            |
| `CDS_ADT`   | 🔒 Fail-closed | Architecture reserve                                                             |
| `REST_JSON` | 🔒 Fail-closed | Architecture reserve                                                             |
| `SQL_READ`  | 🔒 Fail-closed | Architecture reserve                                                             |

### Current Runtime Maturity

- **Offline end-to-end governed composition is implemented and working**: intent → CallPlan → validation/execution → ExecutionResult → ReasoningFact → narrative → durable Workbench replay → plan-aware single Action continuation. The single-capability `CallPlan` main chain remains available.
- **Python Agent responsibilities**: LLM-first intent, closed-set recall, five-state decisioning, and PlanGraph v2 authoring; runs either as a subprocess spawned on demand by the Next server or standalone via the CLI.
- **The DSH harness is wired up**: both DSH Chat (`/chat`) and the harness-dsh CLI enter through the Semantic Tool contract v2 into the same governed entry; model streaming (two-phase reasoning/answer), tool cards, SSE streaming, approval handles, and multi-conversation storage are live.
- **TypeScript composition coordinator**: Wires up PlanExecutor, OutputProjection, Recommendation, grounded Narrative, durable Workbench replay, and plan-aware single-Action continuation.
- **Release gate milestone**: The offline L1/L2/L3 gate reached `22/22` on 2026-08-19, with the highest consecutive level `L3_ACTION_GOVERNED`; headline hard gates are leakage `0`, approval bypass `0`, unsupported claim `0`, lineage `100%`. The earlier 2026-08-10 `22/22` report came from a code state that never entered commit history (its codeVersion is absent from git); it cannot be reproduced and is not a current-status reference.
- **Current architectural limits (design choices, not defects)**:
  - Run/Session, principal ownership, approval, lease/idempotency, and cursor SSE are durable; but the current local JSONL/file store and placeholder principal are still not a shared multi-worker/HA store or a production identity system (mandatory before a second host — see the target architecture's supporting plane)
  - The compile-time derivation pipeline (Capability Manifest), business-semantic `Definition` objects, field-level FactType schema, and relation graph remain target-state work; today's registry is still an endpoint-level capability registry
  - Knowledge/RAG, free-form Tool Calling, a general Dynamic Planner, multi-WRITE/Saga, and automatic compensation remain Reserved / Not In Scope
  - Graph databases and OWL reasoning runtime are reserved directions; JSON Schema + Registry Validator currently carry consistency duties
- **SAP connectivity** (per `runtime/gateway-jco/traces.jsonl`): all four MM capabilities (`MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`, `MM.Material.GetInfo`, `MM.PR.CreateDraft`) have successful real-SAP execution records; the OData chain passed another end-to-end live smoke on 2026-09-13 (real purchase-order rows returned). `SD.SalesOrder.GetList` has live attempts but none succeeded against the current system; `FI.AR.GetOpenItems` / `FI.AP.GetOpenItems` are registered and covered by offline tests but have no live execution record yet — SD/FI live smoke tests remain to be done. The offline release gate's `liveSmoke` field stays `not_run` by design; any live WRITE still requires exact-subject Human Approval.

### Target Achievement Status (S1–S5)

Current implementation assessed against the target architecture's S1–S5 build sequence (re-verified 2026-09-13); full status tables are in [roadmap §1.1](docs/wiki/sap-nexus-agent-implementation-roadmap.md).

- **Sequence progress**: S1 evidence complete · S2 (object keys + field-level schema) not started · S3 (definitions + relations into the ontology + compile-time pipeline) not started · **S4 capability-granularity lift complete, but it jumped over S2/S3** · S5 multi-host validation partially done (cross-host consistency gate 4/4; MCP exposure and a third-party harness not done).
- **Layer status**: the harness experience layer, the contract boundary (four red lines), the SAP domain capability layer (4 business-semantic tools, 3 READ + 1 WRITE), and the Java Gateway with executors (JCO_RFC/ODATA live) are **built**; the compile-time derivation pipeline and runtime-state layer are **partial** (a hand-written versioned JSON Schema contract `contractVersion=2` exists; local JSONL store + placeholder principal); **the capability ontology (objects/definitions/relations) and the offline decision-feedback loop are untouched — the ontology is the one layer not yet on duty**.
- **Three structural requirements**: ① granularity "**achieved, but misplaced**" (the 4 business tools exist but are declared in server code, not in the ontology; endpoint-level tools are no longer external); ② semantic assets **not achieved** (field-level schema, business definitions, and relations are all empty; tool descriptions remain hand-written); ③ identity & approval **partial** (approval handles and server-side identity injection exist; caller principal is still a placeholder and storage is local).
- **Next steps are backfill, not new construction**: ① put a CI gate requiring every new capability output field to reference a `Definition` id (placeholder ids acceptable initially); ② split `ontology-core` (open-source) from `ontology-tenant` (kept private) as early as possible — cheapest while the ontology is nearly empty; ③ lift the definitions of the 4 existing capabilities (available stock / overdue / exposure) out of code one by one, producing field-level schema and the first cross-domain link.
- **The one real break point**: business semantics are fixed in server-side code; the self-check "change one ontology line and Agent behavior changes with zero code changes" does not yet pass.

---

## Harness-Visible Surface: Business Semantic Tools (Contract v2)

The harness may name only business tools and slots; internally the server selects a capability chain from the registered capabilities — the harness never builds the call graph.

| Semantic tool | Required slots | Kind | Server-side capability chain (registry-selected) |
| --- | --- | --- | --- |
| `diagnose_material_supply` | — | READ | stock availability + open purchase orders (`MM.Inventory.GetAvailability` · `MM.PurchaseOrder.GetList`) |
| `review_customer_exposure` | `customerNumber` (company code additionally needed for AR items) | READ | sales-order net values + open AR items (`SD.SalesOrder.GetList` · `FI.AR.GetOpenItems`) |
| `review_vendor_exposure` | `vendor` · `companyCode` | READ | open AP items (`FI.AP.GetOpenItems`) |
| `propose_replenishment` | `material` · `plant` · `requiredQuantity` · `targetDate` · `purchasingGroup` | WRITE draft | gap diagnosis → purchase requisition proposal; exact-subject human approval before execution (`MM.PR.CreateDraft`) |

> Note: the table reflects the capability chains the server actually selects today. In the target architecture, `review_vendor_exposure`'s internal chain additionally includes a purchase-order endpoint; that is not yet internalized. The harness-visible surface has dropped from 7 endpoint-level tools to these 4 business-semantic tools (visibility governance caps the surface at 15).

---

## Registered Capabilities (Server-Side Internals)

| Capability ID                  | Name                                                | Executor  | SAP Endpoint                    | Status                                        |
| ------------------------------ | --------------------------------------------------- | --------- | ------------------------------- | --------------------------------------------- |
| `MM.Inventory.GetAvailability` | Stock/Requirements List (MD04)                      | `JCO_RFC` | `BAPI_MATERIAL_STOCK_REQ_LIST`  | ✅ active                                      |
| `MM.PurchaseOrder.GetList`     | Purchase Order List                                 | `ODATA`   | `API_PURCHASEORDER_PROCESS_SRV` | ✅ active                                      |
| `MM.Material.GetInfo`          | Material Info (base UoM / purchasing group)         | `JCO_RFC` | `BAPI_MATERIAL_GET_DETAIL`      | ✅ active                                      |
| `MM.PR.CreateDraft`            | PR Create Draft                                     | `JCO_RFC` | `BAPI_PR_CREATE`                | ✅ active (requires approval)                 |
| `SD.SalesOrder.GetList`        | Sales Order List (VA05-style)                       | `JCO_RFC` | `BAPI_SALESORDER_GETLIST`       | ✅ active (live smoke pending)                 |
| `FI.AR.GetOpenItems`           | Customer Open Receivables                           | `JCO_RFC` | `BAPI_AR_ACC_GETOPENITEMS`      | ✅ active (live smoke pending)                 |
| `FI.AP.GetOpenItems`           | Vendor Open Payables                                | `JCO_RFC` | `BAPI_AP_ACC_GETOPENITEMS`      | ✅ active (live smoke pending)                 |

7 capabilities: 6 read-only (`kind: Function`, `sideEffect: none`) plus one write
(`MM.PR.CreateDraft`), which cannot execute without a recorded human confirmation.

---

## Repository Layout

```text
agent/                   Python Agent package: intent, CallPlan/PlanGraph v2, tests, evals
frontend/                Next.js: DSH Chat (/chat), classic Workbench (/workbench),
                         semantic-tool facade, server-side dsh runtime, composition runtime
harness-dsh/             Replaceable-harness pilot: standalone Node CLI (dsh T-A-O, pinned 0.1.5-rc.1)
services/
  gateway/               Java Spring Boot SAP Gateway (multi-module, the only security boundary)
  odata-service/         Python OData read-only microservice (:8081)
registry/                Capability registry and executor binding catalog (single YAML source)
schemas/                 JSON Schema contracts
ontology/                Offline OWL identity skeleton (reserved)
openspec/                Classic-workflow specs and change archive
runtime/                 Runtime traces, dev-services, gateway-jco, release-gate results
evals/                   Agent eval cases
scripts/                 Verification and registry validation helpers
docs/
  wiki/                  Architecture, roadmap, technology selection (source of truth)
  comet/                 Native-workflow change archive
  runbooks/              22 historical runbooks (archived; supplementary lookup only, not a fact source)
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
- An OpenAI-compatible LLM endpoint and API key (for DSH Chat / harness-dsh; Rule mode and offline tests need neither)

Fast tests do not require SAP connectivity or credentials.

### Environment Setup

```bash
cp .env.example .env
# Fill in SAP connection parameters; for DSH also set SAP_NEXUS_LLM_BASE_URL / SAP_NEXUS_LLM_API_KEY / SAP_NEXUS_LLM_MODEL
```

### Verification Baseline (as of 2026-09-13)

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests
PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh
npm --prefix frontend run verify
npm --prefix frontend run release-gate -- --profile all
```

Current baselines:

- Registry contract validation: `Registry contract valid` (only 2 deprecation warnings)
- Agent test suite: `1574 passed, 1 skipped, 2 xfailed`
- Frontend suite: `579 passed` (64 test files); `verify` (typecheck + vitest + next build) all green
- Call-plan Evals: inventory `7/7`, eval_harness_seed_cases `13/13`, PR `9/9`, matcher `23/23`, dry-run `3/3` (plus 1 documented structural pending), derived-parameter `3/3` (plus 2 parser-blocked pending cases with written cause analysis)
- Offline release gate: `22/22` / `L3_ACTION_GOVERNED` reached 2026-08-19 (historical milestone)

`PYTHONPATH=agent` verifies the current source tree directly.

### Launch Services

Terminal 1 — Gateway:

```bash
set -a; . ./.env; set +a
cd services/gateway
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
  /tmp/gradle-8.8/bin/gradle --no-daemon bootRun
```

Terminal 2 — OData microservice (required for the purchase-order capability):

```bash
cd services/odata-service
PYTHONPATH=. python -m odata_service.server   # :8081
```

Terminal 3 — DSH Chat (recommended entry; requires an LLM key):

```bash
set -a; . ./.env; set +a
SAP_NEXUS_AGENT_ROOT=$(pwd) \
SAP_NEXUS_GATEWAY_URL=http://127.0.0.1:8080 \
npm --prefix frontend run dev
```

Open `http://127.0.0.1:3000/chat` (the root path redirects there; the classic Workbench remains at `/workbench`).

Optional — harness-dsh standalone CLI (separate terminal; the Next facade above must be running):

```bash
cd harness-dsh
npm ci && npm run build
cp .env.example .env      # OpenAI-compatible endpoint/key; SAP_NEXUS_FACADE_URL defaults to http://127.0.0.1:3000
npm start -- "Does A100 have enough stock at plant 1000, and how much is in transit?"
```

Optional — Python Agent CLI (no harness; Rule mode needs no LLM key):

```bash
PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.cli \
  "How much available stock does A100 have at 1000?" \
  --gateway-url http://127.0.0.1:8080 --intent-mode rule
```

---

## Tech Stack

| Layer                          | Technology                                                                                                                                                    |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Harness                        | DSH Chat (in-Next dsh runtime, SSE streaming) + standalone harness-dsh CLI; `@deepseek-ai/dsh-*` pinned `0.1.5-rc.1`, cordis `4.0.2`; harness replaceable     |
| Agent                          | Python package + OpenAI-compatible LLM (DeepSeek `deepseek-chat` by default) + Rule hybrid                                                                    |
| Server orchestration           | React/Next.js server side: Semantic Tool Facade, Composition Runtime, durable JSONL stores                                                                    |
| Gateway                        | Java 17 / Spring Boot / Gradle multi-module (the only security boundary)                                                                                      |
| SAP Connectivity               | SAP JCo 3 (RFC) + SAP OData (HTTP via odata-service)                                                                                                          |
| Frontend                       | React / Next.js / TypeScript                                                                                                                                  |
| Capability Registry            | YAML + JSON Schema                                                                                                                                            |
| Ontology                       | YAML + JSON Schema + immutable in-memory graph; offline OWL skeleton; graph database and compile-time derivation pipeline are target-state                    |
| Runtime State                  | Local JSONL/file-backed Run/Session/Approval + JSONL traces; not a shared multi-worker/HA store; shared/production durable runtime requires a separate change |
| Authentication & Authorization | Placeholder principal, not productized; shared environments require server-owned principal / tenant / role / data scope / ApprovalActor                      |

---

## Documentation

- [Technical Architecture](docs/wiki/sap-nexus-agent-technical-architecture.md)
- [Implementation Roadmap](docs/wiki/sap-nexus-agent-implementation-roadmap.md)
- [Technology Selection](docs/wiki/sap-nexus-agent-technology-selection.md)
- [OpenHarness Semantic Orchestration Analysis](docs/wiki/sap-nexus-agent-openharness-semantic-orchestration.md)
- [harness-dsh README](harness-dsh/README.md)

---

## License

This project is licensed under [Apache-2.0](LICENSE).

---

## Quick Links

|                          |                                                              |
| ------------------------ | ------------------------------------------------------------ |
| AGENTS.md / CLAUDE.md    | Project-level agent behavioral rules                         |
| registry/                | Capability registry (7 registered capabilities)              |
| harness-dsh/             | The replaceable harness (DSH CLI)                            |
| frontend/src/server/dsh/ | Server-side dsh runtime and semantic-tool wiring             |
| ontology/                | OWL ontology skeleton                                        |
| evals/                   | Evaluation test cases                                        |
