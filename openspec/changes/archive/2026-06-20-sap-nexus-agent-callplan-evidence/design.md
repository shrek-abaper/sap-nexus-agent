## Context

`sap-nexus-capability-registry-gateway` is complete and archived. The current Gateway contract exposes only capability-level APIs and the active `MM.Inventory.GetAvailability` Function through Registry-backed validation and execution. The next risk is not JCo connectivity; it is proving that the Python Agent can plan, validate, execute, evidence, narrate, and evaluate a read-only SAP capability without becoming a generic LLM tool-calling wrapper.

This change builds the first Python Agent vertical slice:

```text
Chinese user intent
-> Intent Harness
-> closed-set Capability Selection
-> CallPlan
-> Java Gateway validate / execute
-> ExecutionResult
-> ReasoningFact
-> Chinese Narrator
-> Eval / Trace evidence
```

The Agent consumes the existing Registry and Gateway behavior. It does not change Gateway endpoints, Registry executor mappings, or SAP JCo connectivity.

## Goals / Non-Goals

**Goals:**

- Parse Chinese inventory availability queries into `material`, `plant`, and optional `unit`.
- Select only `MM.Inventory.GetAvailability` from the Registry closed set for inventory availability intent.
- Clarify missing `material` or `plant` before Gateway validate or execute.
- Generate a structured CallPlan before any executable Gateway call.
- Call the Java Gateway validate / execute APIs by `capabilityId`.
- Parse Gateway `ExecutionResult` and convert it into `ReasoningFact`.
- Render Chinese narrative only from `ReasoningFact` fields.
- Provide fast tests and eval cases that do not require live SAP by default.
- Keep live Gateway smoke optional and explicitly separated from fast verification.

**Non-Goals:**

- No SAP Write Action.
- No `RecommendationPlan`.
- No ML uncertainty reasoning.
- No Knowledge Graph runtime.
- No UI.
- No multi-domain orchestration.
- No raw RFC execution or Agent-provided `rfcName`.
- No changes to the completed Gateway / Registry implementation except consuming its public contract.

## Decisions

### Decision 1: Start with deterministic parser and closed-set selector

The MVP Agent will use deterministic intent parsing and closed-set selection instead of an LLM-first router. The selector may only return `MM.Inventory.GetAvailability` when inventory availability intent is recognized and required parameters are present.

Alternatives considered:

- **LLM-first selection**: more flexible, but increases prompt and hallucination risk before the deterministic harness exists.
- **Gateway-only validation**: simpler, but would allow preventable missing-parameter calls to cross the Agent boundary.

Rationale: deterministic parsing proves the harness and evidence chain first. Future LLM support can be added behind the same closed-set selector contract.

### Decision 2: CallPlan is created before Gateway validate

The Agent will create a CallPlan once intent, capability, and parameters are sufficient to attempt execution. The same `traceId` is then used for Gateway validate and execute when the Gateway contract supports trace propagation or correlation.

Alternatives considered:

- **Create CallPlan after validate**: loses evidence that the Agent planned the call before crossing the Gateway boundary.
- **Only rely on Gateway trace**: omits Agent-side intent, parameter-source, and selection evidence.

Rationale: the project rule is that every action must be planned, validated, executed, normalized, evidenced, audited, and replayable.

### Decision 3: Fast tests use fake Gateway client, live smoke is optional

Unit tests and evals will use a fake Gateway client or fixtures by default. A live smoke can run against `http://localhost:8080` when the Gateway and SAP environment are available.

Alternatives considered:

- **Require live Gateway for all evals**: closer to production, but brittle and blocks local iteration without SAP credentials and JCo native library.
- **Only fixtures forever**: fast, but misses integration regressions.

Rationale: fast verification must be deterministic and safe, while live smoke remains available as extra evidence.

### Decision 4: Narrator consumes ReasoningFact only

The Chinese narrator receives normalized facts, not raw SAP output or free-form Gateway response bodies. It must not invent quantities, units, plant, material, or SAP messages absent from the facts.

Alternatives considered:

- **Narrate directly from ExecutionResult**: fewer objects, but bypasses the evidence layer.
- **LLM narrative over raw response**: expressive, but increases unsupported-claim risk.

Rationale: facts are the evidence boundary for later reasoning and audit.

### Decision 5: Runtime traces are generated locally but not committed

The implementation may write generated callplans, facts, eval outputs, and traces under ignored `runtime/` paths. Tests should assert redaction behavior using fixtures, not committed runtime output.

Alternatives considered:

- **Commit sample runtime traces**: useful examples, but risks stale or sensitive artifacts.
- **No runtime files at all**: safe, but weakens replay design.

Rationale: runtime evidence is important, but generated traces must stay local unless intentionally curated as safe fixtures.

## Risks / Trade-offs

- Agent parser may miss valid Chinese phrasings -> mitigate with eval cases and keep parser rules easy to extend.
- Fake Gateway tests may diverge from live Gateway behavior -> mitigate with optional live smoke against the archived Gateway contract.
- CallPlan trace correlation depends on Gateway request/response fields -> mitigate by preserving Agent-side `traceId` and storing Gateway-returned `traceId` in evidence when different.
- Narrator guard could be too restrictive -> mitigate by adding explicit fact fields for every allowed narrated value.
- New Python dependencies could complicate bootstrap -> mitigate by preferring standard library for HTTP/CLI where practical and documenting any dependency in `agent/pyproject.toml`.

## Migration Plan

1. Add the Agent package, schemas, eval cases, and tests on the current branch.
2. Keep existing Gateway and Registry behavior unchanged.
3. Run fast Agent tests and OpenSpec validation.
4. Optionally run live smoke if the local Gateway and SAP environment are available.
5. If rollback is needed, remove the new Agent/eval/schema files and keep the archived Gateway baseline intact.

## Open Questions

- Whether the implementation should use standard-library `urllib` for the first Gateway client or add `httpx` for cleaner testability.
- Whether the first version should persist local JSONL callplans/facts by default or expose persistence behind an explicit CLI flag.
