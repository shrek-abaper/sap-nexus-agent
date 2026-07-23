## Design

### Architecture

The Workbench remains a local Next.js console, but its Agent Runtime Adapter changes from fake event generation to a local process bridge:

```text
Workbench UI
-> Next.js API route
-> Agent Runtime Adapter
-> local Python Agent structured runner
-> Python Agent hybrid intent adapter
-> Gateway validate / execute
-> Java JCo Gateway
-> SAP BAPI/RFC read
-> ExecutionResult / ReasoningFact / Chinese narrative
-> redacted Workbench artifacts
-> SSE event stream
```

UI components continue to depend only on Workbench API routes and the SSE stream. They never receive controls for `rfcName`, Gateway URL overrides, SAP destination properties, credentials, or raw trace files.

### Python Structured Runner

Add a small serialization layer around the existing `run_inventory_query()` orchestration. It returns JSON-safe camelCase fields for Workbench consumption:

- `status`, `message`, `responseText`, `errorType`, `missingParameters`
- `callPlan`
- `validationResult`
- `executionResult`
- `fact`
- `gatewayTraceId`

The runner must not serialize `.env`, SAP passwords, destination config, tokens, LLM API keys, or raw live LLM responses.

### Next.js Runtime Adapter

The Adapter invokes the Python runner with:

```text
python -m sap_nexus_agent.cli <query> --gateway-url <url> --intent-mode <mode> --json
```

Configuration uses environment variables inherited from `start.sh`:

- `SAP_NEXUS_AGENT_ROOT` defaults to the repository root.
- `SAP_NEXUS_AGENT_PYTHON` defaults to `.venv/bin/python` when present, otherwise `python3`.
- `SAP_NEXUS_GATEWAY_URL` defaults to `http://127.0.0.1:${GATEWAY_PORT:-8080}`.
- `SAP_NEXUS_INTENT_MODE` defaults to `hybrid`.

The Adapter builds ordered Workbench events from structured outcome data and applies the existing redaction guard before artifacts reach the UI.

### Error Handling

- Raw `rfcName` override remains rejected before any runner invocation.
- Python runner JSON with `status=clarification` or `status=failure` is rendered as a safe Workbench timeline, not as a transport crash.
- Runner process crashes, invalid JSON, or missing executable become `run_failed` with a safe `AGENT_RUNTIME_ERROR` message.
- SAP/Gateway business errors are shown through normalized `errorType`, messages, and failed timeline state.

### Verification

Tests use fake runner injection and fake Gateway clients; live SAP and live LLM credentials are not required for automated checks. Manual validation can use `./start.sh`, then submit a real inventory query in the Workbench and compare the returned quantity/error with SAP.
