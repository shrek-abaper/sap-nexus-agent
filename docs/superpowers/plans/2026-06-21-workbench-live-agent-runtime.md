# Workbench Live Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Workbench fake inventory run with a live local Agent Runtime Adapter that invokes the existing Python Agent and Java Gateway for read-only SAP inventory queries.

**Architecture:** Next.js remains the UI/SSE host. The runtime adapter invokes a Python structured runner, which reuses `run_inventory_query()` and Gateway `validate` / `execute`; frontend tests inject fake runner output to stay offline.

**Tech Stack:** Python 3.12, existing `sap_nexus_agent` package, Next.js 15, TypeScript, Vitest, OpenSpec.

---

### Task 1: Python Structured Output

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Create: `agent/sap_nexus_agent/workbench_output.py`
- Modify: `agent/sap_nexus_agent/cli.py`
- Test: `agent/tests/test_workbench_output.py`

- [ ] Write a failing test that serializes a successful fake Gateway outcome with `validationResult`, `executionResult.data.availableQuantity`, `fact`, and `responseText`.
- [ ] Run `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_workbench_output.py -q` and confirm it fails because the module does not exist.
- [ ] Add `validation_result` to `AgentOutcome` and populate it after Gateway validation.
- [ ] Implement `workbench_output.py` with `run_workbench_query()` and `outcome_to_workbench_dict()`.
- [ ] Add `--json` to `sap_nexus_agent.cli` so the frontend can parse structured output.
- [ ] Re-run the focused Python test and confirm it passes.

### Task 2: Frontend Live Runner Adapter

**Files:**
- Modify: `frontend/src/runtime/agent-runtime-adapter.ts`
- Modify: `frontend/app/api/agent-runs/route.ts`
- Test: `frontend/tests/runtime/agent-runtime-adapter.test.ts`

- [ ] Rewrite the adapter test so `createAgentRun()` uses injected runner output with quantity `7`, asserts no `agent-demo-trace`, and asserts the runner receives the query.
- [ ] Run `npm --prefix frontend run test -- --run frontend/tests/runtime/agent-runtime-adapter.test.ts` and confirm it fails against the fake adapter.
- [ ] Replace `buildFakeEvents()` with `runLocalPythonAgent()` and `buildEventsFromOutcome()`.
- [ ] Keep `rfcName` rejection synchronous before invoking the runner.
- [ ] Update the API route to await `createAgentRun()`.
- [ ] Re-run the focused frontend test and confirm it passes.

### Task 3: Launcher And Docs

**Files:**
- Modify: `start.sh`
- Modify: `docs/runbooks/03-agent-workbench-console.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`

- [ ] Export `SAP_NEXUS_AGENT_ROOT`, `SAP_NEXUS_AGENT_PYTHON`, `SAP_NEXUS_GATEWAY_URL`, and `SAP_NEXUS_INTENT_MODE` from `start.sh` without printing secret values.
- [ ] Update docs to clarify local-first means local console/processes, not simulated SAP data.
- [ ] Add manual validation steps for WSL browser users.
- [ ] Run shell syntax and documentation/OpenSpec validation.

### Task 4: Verification

**Files:**
- Modify: `openspec/changes/sap-nexus-workbench-live-agent-runtime/tasks.md`

- [ ] Run `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_workbench_output.py agent/tests/test_orchestrator.py -q`.
- [ ] Run `npm --prefix frontend run test`.
- [ ] Run `scripts/verify-agent-callplan-evidence.sh`.
- [ ] Run `npm --prefix frontend run verify`.
- [ ] Run `openspec validate --all --strict`.
- [ ] Mark all OpenSpec tasks complete only after commands pass or clearly document blockers.
