# AGENTS.md

Project overlay for coding agents working in sap-nexus-agent.
Intentionally avoids repeating user-level guidance in `~/.agents/AGENTS.md`.
Keep only durable, actionable project rules here. Background knowledge lives in `docs/wiki/`.

---

## 0. Precedence & Default Mode

Default = **execute directly**. This project overrides user-level §1 / §3
confirmation defaults (project wins per the user-level conflict rule;
user-level §6 Safety remains non-overridable).

- Do NOT enter "plan-mode-and-wait" for non-trivial tasks by default.
- Reversible task + clear success criteria → proceed autonomously; state
  assumptions inline in one line, NO confirmation round-trip.
- Stop and wait ONLY when a HEAVY or `[BLOCKED]` signal in §3 fires.
- When proceeding, surface key artifacts (diff, test output) for review.
  Never treat "it ran without error" as "it is correct".

---

## 1. Reference Docs (on demand only)

> **Do NOT auto-load reference docs. Load only when the task requires
> architecture or planning decisions.**

Key files (read on demand):
- `docs/wiki/sap-nexus-agent-technical-architecture.md`
- `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- `docs/runbooks/README.md` — then open the current workstream runbook

If this file and wiki docs disagree, follow the wiki docs.

---

## 2. Hard Boundaries

**Capability execution:**
- LLM selects from registered capabilities only; never generate arbitrary RFC names.
- Gateway accepts `capabilityId` only, never request-provided `rfcName`.
- Missing or invalid required parameters must stop execution before reaching SAP.

**SAP execution:**
- READ capabilities MUST NOT call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`.
- WRITE capabilities MUST NOT execute until Human Approval is confirmed for that capability.

**Sensitive data:**
- Never commit `.env`, credentials, tokens, LLM API keys, or runtime traces.
- `.env.example` may contain placeholders only.

---

## 3. Routing (opt-in) & Workflow

**Git:**
- Work on the currently checked-out branch; do not create, switch, or rename
  branches unless explicitly asked.
- Do not commit unless explicitly asked.
- Run `git status --short` before and after non-trivial edits.

### Routing — default is execute directly

Emit `[ROUTE]` and wait for confirmation ONLY if a HEAVY signal fires.
Otherwise build directly, no scoring, no `[ROUTE]`.

**HEAVY signals (any one → route):**
- Structural schema / OWL / Neo4j migration
  (NOT plain registry read/write; NOT capability param / display name / description edits)
- Touches > 2 modules AND > 5 files
- Requirements genuinely ambiguous — design exploration needed
- SAP WRITE path (still gated by Human Approval regardless)

`[ROUTE]` format:
```
[ROUTE] Path: {comet | comet-tweak} | Trigger: {which HEAVY signal} | Reason: {one sentence}
```

**`[BLOCKED]` stop conditions (raise before routing):**
- Task references an undefined capability or unknown RFC name
- Task would touch SAP WRITE path without confirmed Human Approval
- Ontology class / property rename or deletion with unclear blast radius
- Scope ambiguous across ≥ 3 modules

**Path selection (only when a HEAVY signal fired):**

| Signal profile                                                                                | Path                                                         |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Structural schema/ontology migration, OR (>2 modules AND >5 files) needing design exploration | `/comet` — open → design → build → verify → archive          |
| A single bounded HEAVY signal                                                                 | `/comet-tweak` — build → verify → archive                    |
| No HEAVY signal                                                                               | Execute directly, emit one `[NOTE]` line summarising changes |

### Closeout — tiered, NOT per task

- **Per task:** emit one `[NOTE]` line; run only the relevant verify (§4).
- **Per workstream archive ONLY:** update runbook + `docs/runbooks/README.md`,
  update roadmap / wiki progress with links, then run
  `openspec list --json && openspec validate --all --strict`.

---

## 4. Verification (run only what the change touches)

Always:
```
git status --short
```

Then, by change type:
- Schema / registry / ontology change → `openspec list --json && openspec validate --all --strict`
- Frontend change → `npm --prefix frontend run verify`
- Agent call-plan change → `scripts/verify-agent-callplan-evidence.sh`

Do not run the full suite for edits it doesn't touch.
Do not claim success without running the relevant command and checking output.

---

## 5. Communication

- Respond in Chinese unless asked otherwise.
- Use English for code, identifiers, filenames, env vars, and comments.
- State assumptions and success criteria in one line before non-trivial implementation.
- Mention exact file paths changed when updating docs or architecture.
