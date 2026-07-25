# Agent Workbench Console Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `03-agent-workbench-console` |
| Version | `v1.0.5` |
| Status | `Archived` |
| Created | `2026-06-20` |
| Updated | `2026-07-25` |
| Workstream | Internal Agent console, runtime streaming, observability, trace, and human-in-the-loop state skeleton |
| Related Change | `sap-nexus-agent-workbench-console`; corrections: `sap-nexus-workbench-live-agent-runtime`, `sap-nexus-inventory-md04-stock-req-list`; UI layout evolution: `workbench-notion-chat-layout` |
| Current Phase | Workbench baseline archived; Notion-style chat layout evolution archived (2026-07-09) |

---

## 1. Session Goal

Historical goal for this completed workstream:

```text
sap-nexus-agent-workbench-console
```

Target product path:

```text
Natural language input
-> Agent Runtime Adapter
-> SSE event stream
-> Agent run state machine
-> Timeline visualization
-> CallPlan / ExecutionResult / ReasoningFact panels
-> Chinese narrative panel
-> Trace / audit viewer
-> Human-in-the-loop state skeleton
```

The first delivery runs as a local development experience, but local-first means local UI and local service processes. It must still use the real controlled Agent runtime for read-only inventory queries when SAP and LLM credentials are available; it must not return deterministic fake SAP quantities.

Current baseline status:

```text
sap-nexus-agent-workbench-console -> completed, verified, merged to main, archived
archive path -> openspec/changes/archive/2026-06-21-sap-nexus-agent-workbench-console/
main spec -> openspec/specs/agent-workbench-console/spec.md
verification report -> docs/superpowers/reports/2026-06-21-sap-nexus-agent-workbench-console-verify.md
next workstream -> docs/runbooks/04-registry-ontology-contract.md
```

Runtime correction status:

```text
sap-nexus-workbench-live-agent-runtime -> completed, verified, archived
archive path -> openspec/changes/archive/2026-06-22-sap-nexus-workbench-live-agent-runtime/
goal -> Workbench local UI invokes Python Agent structured runner, which calls Java Gateway validate / execute and live SAP JCo Read Function
reason -> archived Workbench baseline used deterministic fake event data; availableQuantity=12 was not a SAP result

sap-nexus-inventory-md04-stock-req-list -> completed, verified, archived
archive path -> openspec/changes/archive/2026-06-22-sap-nexus-inventory-md04-stock-req-list/
goal -> MM.Inventory.GetAvailability uses BAPI_MATERIAL_STOCK_REQ_LIST and extracts MRP_IND_LINES current stock AVAIL_QTY1
```

---

## 2. Current Baseline

Completed and archived:

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
```

Implemented backend baseline:

- `agent/` implements read-only `MM.Inventory.GetAvailability` orchestration.
- CLI default intent mode is `hybrid`: real OpenAI-compatible LLM first, deterministic rule fallback.
- Python Agent creates CallPlan, calls Java Gateway validate / execute, normalizes `ExecutionResult`, builds `ReasoningFact`, and renders Chinese narrative.
- Java Gateway exposes capability-ID-only validate / execute and writes JSONL trace records.
- Runtime traces and local outputs remain ignored and must not be committed.
- Workbench read-only inventory submissions must call the local Python Agent structured runner and display Agent/Gateway/SAP results, safe Gateway errors, or clarifications. They must not display hardcoded fake inventory data.

Verified baseline:

```text
scripts/verify-agent-callplan-evidence.sh
-> 41 passed, 1 skipped
-> Eval passed: 7/7
-> openspec validate --all --strict: 3 specs passed, 0 active changes
```

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
docs/runbooks/03-agent-workbench-console.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-technology-selection.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/agent-callplan-evidence/spec.md
```

Expected state:

- Current branch is expected to be `main` unless the user changed it.
- `openspec list --json` should show no active changes before this workstream starts.
- `git status --short` should be clean or contain only user-confirmed local edits.

---

## 4. Proposed Workstream Scope

Build the internal Agent Workbench Console architecture and first local runnable slice.

In scope:

- React + Next.js + TypeScript frontend skeleton.
- Modular Monolith module boundaries for Agent console, runtime timeline, artifacts, trace audit, and human-in-the-loop state.
- Agent Runtime Adapter boundary between Next.js and Python Agent / Java Gateway.
- SSE-first run event stream for observing agent execution.
- Human-in-the-loop state machine skeleton, with read-only queries marked as `approval_not_required`.
- Natural language input for the existing `MM.Inventory.GetAvailability` read capability.
- Visual panels for `IntentParseResult`, capability selection, CallPlan, Gateway validate / execute, `ExecutionResult`, `ReasoningFact`, narrative, and trace IDs.
- Redaction guard for secrets and sensitive runtime details.

Out of scope for the first change:

- Production authentication / RBAC.
- Multi-tenant deployment.
- SAP Write Action execution.
- Real approval-driven SAP writes.
- RecommendationPlan implementation.
- Knowledge Graph runtime.
- Full trace database or log warehouse.
- Arbitrary RFC execution.

---

## 5. Target Frontend Architecture

Use a production-capable internal console architecture, delivered first as a local tool:

```text
frontend/
  app/
    workbench/
      page.tsx
    api/
      agent-runs/
        route.ts
      agent-runs/[runId]/stream/
        route.ts
      traces/[traceId]/
        route.ts
  src/
    modules/
      agent-console/
      runtime-timeline/
      capability-catalog/
      call-plan/
      execution-result/
      reasoning-fact/
      human-approval/
      trace-audit/
      eval-lab/
    runtime/
      agent-runtime-adapter.ts
      run-event-schema.ts
      run-state-machine.ts
      redaction.ts
    shared/
      ui/
      types/
      contracts/
```

SSE should be the default streaming protocol for the first version. WebSocket can be added later when true bidirectional collaboration, approval, cancellation, or multi-turn human input is needed.

---

## 6. Acceptance Criteria

| Area | Acceptance |
|---|---|
| UI shell | Local Next.js Workbench page can submit a Chinese Agent query |
| Runtime adapter | UI calls an Agent Runtime Adapter, which invokes the local Python Agent structured runner; UI does not call Java Gateway or SAP directly |
| Streaming | The run emits ordered SSE events for major execution stages |
| Timeline | UI renders intent, capability selection, CallPlan, Gateway, fact, narration, and completion states |
| HITL skeleton | State machine can represent approval states, while read-only inventory query shows no approval required |
| Trace | UI displays agent trace ID, gateway trace ID, status, error type, and redacted artifact JSON |
| Safety | UI cannot input or override `rfcName`; UI never displays `.env`, SAP password, `LLM_API_KEY`, destination config, or raw secrets |
| Regression | Existing Agent and OpenSpec verification commands still pass |

Recommended verification command shape after implementation:

```bash
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
# plus the frontend test/build command chosen by the change
```

---

## 7. Safety And Workflow Notes

- Do not create or switch branches unless the user explicitly asks.
- Do not commit `.env`, SAP credentials, LLM API keys, tokens, destination config, or runtime traces.
- Do not expose arbitrary RFC execution in UI, API routes, or runtime adapter.
- Do not let frontend input generate or override `rfcName`.
- Treat the Workbench as an internal Agent console; first delivery is local, but boundaries should not block production hardening.
- Treat local-first as a deployment/developer-experience property, not a data simulation policy. Read-only inventory output must come from the controlled Agent/Gateway/SAP path unless a test explicitly injects a fake runner.
- Keep UI as a Modular Monolith; do not introduce frontend microservices.
- Prefer the SSE protocol first, but treat the current buffered SSE-format response as local MVP only; shared runtime requires incremental events plus reconnect/replay. Add WebSocket only when a concrete bidirectional need appears.

## Manual WSL Browser Validation

Use this after `sap-nexus-workbench-live-agent-runtime` changes are present:

1. Start services from WSL:

```bash
./start.sh
```

`start.sh` auto-injects `JAVA_TOOL_OPTIONS=-Djava.library.path=$ROOT/services/gateway/jco/lib/linux` so the Gateway JVM can load `libsapjco3.so`. If a read query fails with `库存查询失败（UNKNOWN）：未提供错误明细`, the JCo native lib is not loading — check `runtime/dev-services/logs/gateway.log` for `UnsatisfiedLinkError` and confirm `SAP_JCO_LIB_PATH` / `JAVA_TOOL_OPTIONS`.

2. Open the Workbench from the Windows browser:

```text
http://127.0.0.1:3000/workbench
```

3. Submit a known read-only inventory query:

```text
<material> 在 <plant> 还有多少可用库存？
```

4. Confirm the timeline shows Gateway validation and Gateway execution with non-demo trace IDs.
5. Compare `ExecutionResult.data.availableQuantity`, `returnMessages`, or the safe failure message with SAP.
6. If SAP has no matching data, the Workbench should show the real Gateway/SAP result or normalized business/error response, not a hardcoded `12 EA`.

---

## 8. Historical First Steps

This workstream is complete. The original first steps were executed through OpenSpec / Comet and are preserved in the archived change package:

```text
openspec/changes/archive/2026-06-21-sap-nexus-agent-workbench-console/
```

Do not reopen this workstream unless a concrete defect is found in the Workbench Console baseline. New Registry / OWL contract work should start from `docs/runbooks/04-registry-ontology-contract.md`.

---

## 9. Prompt To Start The Next Session

Use `docs/runbooks/04-registry-ontology-contract.md` for the next session. The old Workbench startup prompt is superseded because `sap-nexus-agent-workbench-console` is completed, verified, merged to `main`, and archived.

```text
继续 . 项目工作。

请先读取并遵守：
1. AGENTS.md
2. docs/runbooks/README.md
3. docs/runbooks/04-registry-ontology-contract.md
4. docs/wiki/sap-nexus-agent-technical-architecture.md
5. docs/wiki/sap-nexus-agent-technology-selection.md
6. docs/wiki/sap-nexus-agent-implementation-roadmap.md
7. openspec/specs/capability-registry-gateway/spec.md
8. openspec/specs/agent-callplan-evidence/spec.md
9. openspec/specs/agent-workbench-console/spec.md

当前状态：
- sap-nexus-capability-registry-gateway 已完成、验证并归档。
- sap-nexus-agent-callplan-evidence 已完成、验证并归档。
- sap-nexus-agent-llm-intent-adapter 已完成、验证并归档。
- sap-nexus-agent-workbench-console 已完成、验证、合并到 main 并归档。
- Agent 已支持 read-only `MM.Inventory.GetAvailability` 纵切和 `hybrid` LLM intent mode。
- Agent Workbench Console 已提供本地内部控制台基线。
- 不要重复实现 Gateway / Registry execution / JCo connectivity / Python Agent CallPlan / LLM intent adapter / Workbench Console。

今天目标：
启动并推进 OpenSpec / Comet change：sap-nexus-registry-ontology-contract。

开始前请先执行并汇报：
- git status --short
- openspec list --json
- openspec validate --all --strict
- scripts/verify-agent-callplan-evidence.sh
```

## Session Closeout - 2026-06-20

### Completed

- Created and implemented OpenSpec / Comet change `sap-nexus-agent-workbench-console`.
- Added local-first `frontend/` Agent Workbench Console with SSE runtime visualization, redacted artifact panels, trace metadata, and HITL state skeleton.

### Verified

- Command: `npm --prefix frontend run typecheck`
- Result: passed
- Command: `npm --prefix frontend run test`
- Result: passed
- Command: `npm --prefix frontend run build`
- Result: passed
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: passed
- Command: `openspec validate --all --strict`
- Result: passed

### Blockers

- None. PostHog network flush errors appeared after OpenSpec validation, but validation exited 0 with `Totals: 3 passed, 0 failed (3 items)` and are non-blocking by project rule.

### Next Start Here

1. Confirm the archive exists at `openspec/changes/archive/2026-06-21-sap-nexus-agent-workbench-console/`.
2. Review `openspec/specs/agent-workbench-console/spec.md` only when changing Workbench behavior.
3. Use `docs/runbooks/04-registry-ontology-contract.md` for the next recommended workstream.

## Session Closeout - 2026-06-21

### Completed

- Merged `sap-nexus-agent-workbench-console` into local `main`.
- Archived OpenSpec / Comet change at `openspec/changes/archive/2026-06-21-sap-nexus-agent-workbench-console/`.
- Created main spec `openspec/specs/agent-workbench-console/spec.md`.
- Deleted the completed feature branch `feature/20260620/sap-nexus-agent-workbench-console`.

### Verified

- Command: `npm --prefix frontend run verify`
- Result: passed
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: passed
- Command: `openspec list --json`
- Result: `{"changes":[]}`
- Command: `openspec validate --all --strict`
- Result: passed with `spec/agent-callplan-evidence`, `spec/agent-workbench-console`, and `spec/capability-registry-gateway`

### Blockers

- None. PostHog network flush errors appeared after OpenSpec commands, but command exit code was 0 and validation passed.

### Next Start Here

1. Read `docs/runbooks/04-registry-ontology-contract.md`.
2. Confirm `openspec list --json` returns no active changes.
3. Start `sap-nexus-registry-ontology-contract` only after checking `docs/wiki/sap-nexus-agent-implementation-roadmap.md`.

## Session Closeout - 2026-06-22

### Completed

- Archived `sap-nexus-workbench-live-agent-runtime` to `openspec/changes/archive/2026-06-22-sap-nexus-workbench-live-agent-runtime/`.
- Archived `sap-nexus-inventory-md04-stock-req-list` to `openspec/changes/archive/2026-06-22-sap-nexus-inventory-md04-stock-req-list/`.
- Synced main specs for `agent-workbench-console`, `agent-callplan-evidence`, and `capability-registry-gateway`.
- Confirmed live inventory path now returns the SAP MD04 stock/requirements result through `BAPI_MATERIAL_STOCK_REQ_LIST`, not fake Workbench data.

### Verified

- Command: `cd gateway-jco && /tmp/gradle-8.8/bin/gradle --no-daemon test`
- Result: passed
- Command: `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_reasoning_narrator.py agent/tests/test_orchestrator.py agent/tests/test_workbench_output.py -q`
- Result: `19 passed`
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: `41 passed, 1 skipped`; eval `7/7`
- Command: `npm --prefix frontend run verify`
- Result: typecheck, tests, and build passed
- Command: `openspec list --json`
- Result: `{"changes":[]}`
- Command: `openspec validate --all --strict`
- Result: passed with `agent-callplan-evidence`, `agent-workbench-console`, and `capability-registry-gateway`
- Live smoke: Python Agent query `DEMOA1 在 1000 还有多少可用库存？` returned `executor.rfcName=BAPI_MATERIAL_STOCK_REQ_LIST`, `data.availableQuantity=0.0`, `sourceTable=MRP_IND_LINES`, `sourceField=AVAIL_QTY1`, `mrpElementInd=WB`, `mrpElement=Stock`

### Blockers

- None. PostHog network flush errors appeared after OpenSpec commands, but command exit code was 0 and validation passed.

### Next Start Here

1. Read `docs/runbooks/04-registry-ontology-contract.md`.
2. Confirm `openspec list --json` returns no active changes.
3. Start `sap-nexus-registry-ontology-contract` only after checking `docs/wiki/sap-nexus-agent-implementation-roadmap.md`.

## Session Closeout - 2026-07-09 (Notion-style chat layout evolution)

### Completed

- OpenSpec / Comet change `workbench-notion-chat-layout` (tweak workflow): refactored the Workbench frontend from a three-column layout (side-nav / stage / copilot) to a Notion-style two-column chat layout (side-nav / chat stage).
- Empty state centers a single welcome input; conversation state moves the input to a fixed bottom composer; the AI reply streams reasoning steps incrementally with a streaming cursor placeholder until the narrative arrives.
- Structured process evidence (Runtime Timeline, Human-approval, Trace audit, detailed artifact groups) is now collapsible beneath the AI reply bubble, collapsed by default.
- Frontend multi-turn message accumulation with Run History scroll-to-turn switching; each turn remains an independent Agent run without carried backend context.
- Backend APIs, SSE mechanism, run state machine, redaction, and HITL contract unchanged.

### Files

- Modified: `frontend/app/globals.css`, `frontend/src/modules/agent-console/AgentConsole.tsx`, `frontend/src/modules/agent-console/view-model.ts`
- Added: `frontend/src/modules/agent-console/chat-types.ts`, `ChatComposer.tsx`, `ChatStream.tsx`, `tests/agent-console/summarize-turn.test.ts`, `tests/agent-console/chat-bubble-state.test.ts`

### Verified

- Command: `npm --prefix frontend run typecheck`
- Result: passed
- Command: `npm --prefix frontend run test`
- Result: `22 passed` (6 test files; 9 new tests added)
- Command: `npm --prefix frontend run build`
- Result: `Compiled successfully`
- Command: `openspec validate --all --strict`
- Result: `7 passed, 0 failed`
- Command: `scripts/verify-agent-callplan-evidence.sh`
- Result: `109 passed, 1 skipped`; eval `7/7` and `13/13`

### Notes

- Component DOM render tests deferred: the frontend test stack has no jsdom / testing-library dependency; spec scenarios are covered by pure-function tests (`summarizeTurn`, `buildChatBubbleState`) plus typecheck and build. Introducing a DOM test environment is out of scope for this tweak.
- User confirmed continuing the tweak workflow despite the 8-file count exceeding the tweak hint threshold (>6), because no qualitative-change signal was hit (single frontend module, no new capability, no architecture change).
- Code commit deferred per project CLAUDE.md (do not commit unless explicitly asked); changes remain in the worktree.

### Next Start Here

1. Run `node "$COMET_STATE" next workbench-notion-chat-layout` to continue the tweak verify -> archive phases.
2. Archive the change to `openspec/changes/archive/2026-07-09-workbench-notion-chat-layout/` after verify passes.

### Archive Status (2026-07-14 backfill)

The `Next Start Here` steps above were the plan at session close on `2026-07-09`; they have since been completed. Backfilling the true terminal state:

- `workbench-notion-chat-layout` completed verify and archived: `.comet.yaml` shows `phase=archive`, `verify_result=pass`, `archived=true`, `verified_at=2026-07-09`; archive dir `openspec/changes/archive/2026-07-09-workbench-notion-chat-layout/`.
- `openspec list --json` currently returns no active changes.
- Next recommended workstream is `sap-nexus-sandbox-write-vertical-slice` (see `docs/runbooks/README.md`), not a continuation of this workstream.
3. Sync the delta spec into `openspec/specs/agent-workbench-console/spec.md` at archive time.

## Session Closeout - 2026-07-25 (Workbench Hero copy & visual tweak)

Tweak (score 0, execute directly per AGENTS.md routing). Middle-column copy hierarchy and visual style only; no side-nav, agent, gateway, or registry behavior changes.

### Completed

- Task 1 Hero copy hierarchy: H1 -> `用自然语言调用受控 SAP 能力` (no period, single line); subtitle -> `先给结论，再给证据链`; removed the Read/sandbox Action mechanism paragraph (equivalent copy already present in `HumanApprovalPanel`: parameter snapshot dl + `批准并执行` + `Read-only Function，不需要人工审批`); added guard line `未声明的能力不会执行 · 写操作需人工批准` under the input.
- Task 1 Step 1 SKIPPED: eyebrow stays as static decoration. Capability count (`3 online · 2 read · 1 write`) would need to derive from `registry/capabilities.yaml`, but the frontend has no capability API (only `agent-runs` / `traces` routes). Numbers not hardcoded per the no-fabrication rule. Registry actually contains 3 capabilities (`MM.Inventory.GetAvailability` READ, `MM.PurchaseOrder.GetList` READ, `MM.PR.CreateDraft` ACTION); exposing them to the frontend needs a new `/api/capabilities` route, deferred to keep this a tweak.
- Task 2 placeholder: `描述你的 SAP 问题，例如：DEMOA2 在工厂 5100 的可用库存`; identifiers share the new `sample-data.ts` constants.
- Task 3 example cards: one per registered capability - `READ · 库存`, `READ · 采购订单`, `ACTION · 需审批`; label occupies the top row, text left-aligned, identifiers monospace. Card 3 submits via the existing `runAgent` path (no special branch); approval interception depends on backend intent recognition (unchanged).
- Task 4 visual: added tokens `--accent` `#0F766E` / `--accent-hover`, `--tag-read-bg` / `--tag-read-text`, `--tag-action-color` `#D97706`, `--text-subtle` `#6B7280`; updated `--font-mono` to the standardized stack; `.mono-token` reusable monospace class; H1 30px/600/-0.02em/nowrap, subtitle 14px/`#6B7280`, Hero `padding-top 15vh`, middle column `max-width 720px` (hero + chat-stream + composer), input `min-height 96px` / `radius 12px` / focus accent border / no shadow; topbar `● Read 直连 · Write 需审批` status dots (read accent, write amber); READ tag bg `#F3F4F6` dark-gray text no border, ACTION tag amber border no fill. No SAP blue `#0A6ED1`, no purple gradients.
- Task 5 SKIPPED: `AgentRunEvent` / `AgentRunSnapshot` carry no intent-count field (`intent_parsed` only carries an artifact); not modifying backend, not guessing intent count. Tracked as TODO.

### Files

- Modified: `frontend/src/modules/agent-console/AgentConsole.tsx`, `frontend/app/globals.css`, `docs/runbooks/03-agent-workbench-console.md`
- Added: `frontend/src/modules/agent-console/sample-data.ts`
- Unrelated, pre-existing uncommitted: `frontend/src/shared/ui/Icon.tsx` (from the prior side-nav `plus` icon task; not touched in this tweak)

### Verified

- Command: `npm run typecheck` -> passed (exit 0)
- Command: `npm run test` -> `8 files, 33 passed`
- Command: `npm run build` -> `Compiled successfully`, 6 pages generated
- Command: `git diff --check` -> clean (exit 0)
- Note: `npm run lint` not available (no eslint config / lint script in `frontend/`); typecheck + test + build matches AGENTS.md §4 `npm run verify`.

### Blockers

- None. Manual browser validation pending local `npm run dev`: H1 single line, three example cards with correct labels/copy, card 3 enters approval interception, identifiers in monospace, no SAP blue or purple.

### Residual Risks

- Card 3 (ACTION) approval interception depends on the backend intent adapter recognizing `为 DEMOA2 创建采购申请草稿` as `MM.PR.CreateDraft`; if the backend does not, it returns clarification/error via the normal path (no bypass, no special branch).
- H1 `white-space: nowrap` may overflow on extremely narrow viewports (<280px); acceptable for an internal console.
- Eyebrow remains a static decoration (Task 1 Step 1 skipped); the capability-count status line is a future TODO once a capability API exists.
