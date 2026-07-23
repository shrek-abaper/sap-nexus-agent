## 1. Frontend Skeleton And Contracts

- [x] 1.1 Create `frontend/` Next.js + React + TypeScript skeleton with documented local dev and verification commands.
- [x] 1.2 Add Modular Monolith directories for agent console, runtime timeline, artifact panels, trace audit, human approval, runtime contracts, and shared UI/types.
- [x] 1.3 Define `AgentRunEvent` TypeScript contract with event type, run ID, sequence, timestamp, state, trace IDs, safe artifact payload, and error metadata.
- [x] 1.4 Define the Agent run state machine and human-in-the-loop state skeleton, including `approval_not_required` for read-only queries.

## 2. Runtime Adapter And Streaming

- [x] 2.1 Implement an Agent Runtime Adapter boundary that accepts natural language input and blocks or removes raw `rfcName` overrides.
- [x] 2.2 Add local API route to create an Agent run through the adapter.
- [x] 2.3 Add SSE route for ordered run events using the `AgentRunEvent` contract.
- [x] 2.4 Add deterministic fake/local adapter path for tests and development without live SAP or live LLM credentials.

## 3. Workbench User Interface

- [x] 3.1 Build the Workbench page with Chinese natural language input for the existing inventory availability flow.
- [x] 3.2 Render a timeline for intent parsing, capability selection, CallPlan creation, approval state, Gateway validation, Gateway execution, ReasoningFact creation, narration, trace linkage, and completion/failure.
- [x] 3.3 Add redacted artifact panels for CallPlan, ExecutionResult, ReasoningFact, Chinese narrative, and trace metadata.
- [x] 3.4 Add human-in-the-loop panel that shows `approval_not_required` for `MM.Inventory.GetAvailability` and can represent reserved future approval states.

## 4. Safety And Redaction

- [x] 4.1 Implement redaction guard for `.env`, SAP password, destination config, tokens, LLM API keys, raw live LLM responses, and suspicious secret-like fields.
- [x] 4.2 Ensure UI components only render redacted artifacts received from the adapter.
- [x] 4.3 Ensure frontend routes do not expose direct Java Gateway, SAP, or arbitrary RFC execution surfaces.
- [x] 4.4 Confirm generated runtime traces and local live outputs remain ignored and are not committed.

## 5. Verification And Documentation

- [x] 5.1 Add frontend unit tests for event schema, run state transitions, HITL states, and redaction behavior.
- [x] 5.2 Add a frontend build or typecheck command and document it near the `frontend/` subsystem.
- [x] 5.3 Run frontend verification without live SAP credentials, live LLM credentials, raw live LLM responses, or generated runtime traces.
- [x] 5.4 Run `scripts/verify-agent-callplan-evidence.sh`.
- [x] 5.5 Run `openspec validate --all --strict`.
- [x] 5.6 Update `docs/runbooks/03-agent-workbench-console.md` with what changed, what was verified, blockers, and the exact next action.
