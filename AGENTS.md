# AGENTS.md
Project overlay for coding agents working in sap-nexus-agent.

Intentionally avoids repeating user-level guidance in `~/.codex/AGENTS.md`.
Keep only durable, actionable project rules here. Background knowledge lives in `docs/wiki/`.

---

## 0. Task Intake (Mandatory)

Before acting on any task that involves code changes, emit a `[ROUTE]` line and wait for explicit user confirmation.

```
[ROUTE] Path: {choice} | Score: {N} | Reason: {one sentence}
```

---

## 1. Reference Docs (on demand only)

> **Do NOT auto-load reference docs. Load only when the task requires architecture or planning decisions.**

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

## 3. Git and Workflow

- Work on the currently checked-out branch; do not create, switch, or rename branches unless explicitly asked.
- Do not commit unless explicitly asked.
- Run `git status --short` before and after non-trivial edits.

### Comet Routing

**Pre-check — skip routing and execute directly if ANY of the following is true:**
- All changes are limited to `.md` or `.html` files
- No code, schema, registry, config, or binary files are modified
- Change is limited to a single file with no cross-module impact
- Fix is a typo / comment / log message / i18n string only
- Change adds or edits a single capability's parameters / display name / description only — no structural schema change

If pre-check passes → execute directly, no scoring needed, no `[ROUTE]` output required.

**`[BLOCKED]` stop conditions (raise before scoring):**
- Task references an undefined capability or unknown RFC name
- Task would touch SAP WRITE path without confirmed Human Approval
- Involves ontology class/property rename or deletion with unclear blast radius
- Scope is ambiguous across ≥ 3 modules — ask for clarification first

Otherwise score the task, then select the path:

| Criterion                                                                                                                                                                                  | Score |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- |
| Touches architecture / ontology registry / OWL schema / Neo4j migration? Excludes: adding or editing a single capability's parameters, updating registry display name or description only. | +3    |
| Affects more than 5 files OR more than 2 modules?                                                                                                                                          | +2    |
| Requirements unclear — design exploration needed?                                                                                                                                          | +2    |
| Likely to span sessions or require tool switching?                                                                                                                                         | +1    |

| Score | Path                                                         |
| ----- | ------------------------------------------------------------ |
| ≥ 4   | `/comet` — open → design → build → verify → archive          |
| 2–3   | `/comet-tweak` — build → verify → archive                    |
| 1     | Execute directly, emit one `[NOTE]` line summarising changes |
| 0     | Execute directly                                             |

### Comet Closeout

Do NOT declare task complete until all items are done:

- [ ] Update relevant runbook and `docs/runbooks/README.md`
- [ ] Update roadmap / wiki progress; mark workstream archived with links
- [ ] `openspec list --json && openspec validate --all --strict`

---

## 4. Verification

```bash
git status --short
openspec list --json
openspec validate --all --strict
scripts/verify-agent-callplan-evidence.sh
npm --prefix frontend run verify        # frontend changes only
```

Do not claim success without running the relevant command and checking output.

---

## 5. Communication

- Respond in Chinese unless asked otherwise.
- Use English for code, identifiers, filenames, env vars, and comments.
- State assumptions and success criteria before implementation work.
- Mention exact file paths changed when updating docs or architecture.
