## Why

The archived Workbench Console currently renders a deterministic fake Agent run. A user-submitted inventory query can display `availableQuantity: 12` even when SAP has no matching inventory data, because `frontend/src/runtime/agent-runtime-adapter.ts` builds fake local events instead of invoking the existing Python Agent and Java JCo Gateway.

This violates the intended Workbench usage: the console may be local-first, but read-only inventory queries must exercise the real controlled Agent chain when SAP and LLM credentials are available.

## What Changes

- Replace the fake Workbench runtime path with a live local Agent Runtime Adapter that invokes the existing Python Agent structured runner.
- Keep the frontend boundary intact: UI components submit natural language to the Adapter and must not call SAP, Java Gateway, or raw RFC endpoints directly.
- Reuse the existing Python Agent orchestration, hybrid LLM intent adapter, Gateway `validate` / `execute`, `ExecutionResult`, `ReasoningFact`, and Chinese narrator.
- Add structured JSON output for the Python Agent so Next.js can render redacted Workbench artifacts without scraping CLI prose.
- Preserve offline tests through dependency injection / fake runners; normal verification must not require SAP credentials, LLM credentials, raw live LLM responses, or committed runtime traces.
- Keep read-only scope only. This change does not add SAP Write Action, approval writes, RecommendationPlan, KG runtime, RBAC, multi-tenancy, or production deployment.

## Capabilities

### Modified Capabilities

- `agent-workbench-console`: Workbench run submission now must use the real local Python Agent runtime for read-only inventory execution instead of deterministic fake event data.

### Consumed Capabilities

- `agent-callplan-evidence`: Supplies the controlled Python Agent orchestration and evidence model.
- `capability-registry-gateway`: Supplies Java Gateway capability validation, execution, trace, and SAP JCo boundary.

## Impact

- Modifies frontend runtime adapter and API route behavior.
- Adds Python structured runner / JSON serialization for Agent outcomes.
- May update `start.sh` environment wiring so the Workbench can find the local Agent and Gateway URL.
- Updates Workbench spec/runbook/roadmap wording to clarify that local-first does not mean fake SAP data.
- Existing verification remains required:
  - `scripts/verify-agent-callplan-evidence.sh`
  - `npm --prefix frontend run verify`
  - `openspec validate --all --strict`
