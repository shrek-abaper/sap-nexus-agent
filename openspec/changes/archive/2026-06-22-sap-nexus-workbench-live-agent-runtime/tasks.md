## 1. OpenSpec And Plan

- [x] 1.1 Create `sap-nexus-workbench-live-agent-runtime` OpenSpec change.
- [x] 1.2 Document the fake-data root cause and live Agent runtime target.
- [x] 1.3 Add modified Workbench spec scenarios for live Agent runtime execution.

## 2. Python Agent Structured Runner

- [x] 2.1 Add failing Python tests for structured Workbench output from `run_inventory_query()`.
- [x] 2.2 Add `validation_result` to `AgentOutcome` and serialize Workbench-safe JSON.
- [x] 2.3 Add `--json` CLI output for the local Python Agent runner.

## 3. Next.js Runtime Adapter

- [x] 3.1 Add failing frontend tests proving Workbench uses injected live runner data and does not emit fake `12` / demo traces.
- [x] 3.2 Replace `buildFakeEvents()` with a Python runner bridge and structured outcome-to-event mapping.
- [x] 3.3 Preserve raw `rfcName` rejection before runner invocation.
- [x] 3.4 Ensure runner process failures produce safe `run_failed` events.

## 4. Local Launcher And Documentation

- [x] 4.1 Export Agent/Gateway runtime environment from `start.sh` without printing secrets.
- [x] 4.2 Update Workbench runbook and roadmap to state local-first uses live Agent/Gateway/SAP for read-only inventory.
- [x] 4.3 Document manual WSL browser validation steps.

## 5. Verification

- [x] 5.1 Run focused Python tests.
- [x] 5.2 Run focused frontend tests.
- [x] 5.3 Run `scripts/verify-agent-callplan-evidence.sh`.
- [x] 5.4 Run `npm --prefix frontend run verify`.
- [x] 5.5 Run `openspec validate --all --strict`.
