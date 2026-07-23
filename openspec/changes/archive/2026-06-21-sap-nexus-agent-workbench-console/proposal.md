## Why

SAP Nexus Agent now has a verified read-only Agent path, but developers still need a safe internal console to observe the harness chain end to end without inspecting scattered CLI output, Gateway logs, or runtime traces. This change adds a local-first Agent Workbench Console shaped for future production hardening so Agent runs can be visualized, audited, and prepared for human-in-the-loop workflows.

## What Changes

- Add a React + Next.js + TypeScript Workbench skeleton for the existing read-only `MM.Inventory.GetAvailability` Agent flow.
- Add an Agent Runtime Adapter boundary so the frontend starts and observes Agent runs without calling SAP, Java Gateway, or raw RFC endpoints directly.
- Add an SSE-first runtime event stream for ordered Agent run stages.
- Add a run state machine and timeline visualization for intent parsing, capability selection, CallPlan, Gateway validation/execution, fact creation, narration, trace, and completion/error states.
- Add artifact panels for redacted `CallPlan`, `ExecutionResult`, `ReasoningFact`, Chinese narrative, and trace metadata.
- Add a human-in-the-loop state skeleton where read-only inventory queries show `approval_not_required`.
- Add secret redaction rules so the console does not display or persist `.env`, SAP password, destination config, tokens, LLM API keys, raw live LLM responses, or runtime trace contents.
- No SAP write actions, real approval writes, RecommendationPlan, KG runtime, RBAC, multi-tenancy, or production deployment are introduced in this change.

## Capabilities

### New Capabilities

- `agent-workbench-console`: Internal Agent console behavior for local-first Agent run submission, SSE runtime visualization, redacted artifact panels, trace/audit viewing, and human-in-the-loop state skeleton.

### Modified Capabilities

- None. Existing `capability-registry-gateway` and `agent-callplan-evidence` requirements are consumed as the backend baseline and are not changed by this proposal.

## Impact

- Adds a new `frontend/` subsystem with Next.js, React, TypeScript, Modular Monolith module boundaries, API routes, runtime adapter, run event schema, state machine, redaction guard, shared UI/types, tests, and documentation.
- May add frontend package metadata and verification commands without changing existing Python Agent or Java Gateway execution contracts.
- Existing verification must continue to pass:
  - `scripts/verify-agent-callplan-evidence.sh`
  - `openspec validate --all --strict`
- Frontend verification will be added by this change and must not require live SAP credentials, live LLM credentials, committed runtime traces, or sensitive local configuration.
