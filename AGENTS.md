# AGENTS.md

Project overlay for coding agents working in `sap-nexus-agent`.
Intentionally avoids repeating user-level guidance in `~/.agents/AGENTS.md`.
Keep only durable, actionable project rules here. Background knowledge lives in `docs/wiki/`.

Comet is installed with `--workflow both`: **Native** and **Classic** are two independent
workflows with separate entries, state, artifacts, and Guards. Neither upgrades into the other.

---

## 0. Precedence & Default Mode

Default = **execute directly**. This project overrides user-level §1 / §3 confirmation defaults
(project wins per the user-level conflict rule; user-level §6 Safety remains non-overridable).

- Do NOT enter "plan-mode-and-wait" for non-trivial tasks by default.
- Reversible task + clear success criteria → proceed autonomously; state assumptions inline in
  one line, NO confirmation round-trip.
- Stop and wait ONLY when a `[BLOCKED]` condition in §3 fires.
- When proceeding, surface key artifacts (diff, test output) for review.
  Never treat "it ran without error" as "it is correct".
- Inside a Comet change, the workflow owns the decision points. Do not add a second
  confirmation layer on top of them.

---

## 1. Reference Docs (on demand only)

> **Do NOT auto-load reference docs. Load only when the task requires architecture or
> planning decisions.**

Key files (read on demand):

- `docs/wiki/sap-nexus-agent-technical-architecture.md`
- `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- `docs/runbooks/README.md` — then open the current workstream runbook

If this file and the wiki docs disagree, follow the wiki docs.

---

## 2. Hard Boundaries

**Capability execution:**

- LLM selects from registered capabilities only; never generate arbitrary RFC names.
- Gateway accepts `capabilityId` only, never a request-provided `rfcName`.
- Missing or invalid required parameters must stop execution before reaching SAP.

**SAP execution:**

- READ capabilities MUST NOT call `BAPI_TRANSACTION_COMMIT` or `BAPI_TRANSACTION_ROLLBACK`.
- WRITE capabilities MUST NOT execute until Human Approval is confirmed for that capability.
- Human Approval is not a chat sentence. It must exist as a checkable acceptance item:
  "a recorded human confirmation exists for this WRITE capability before execution".

**Sensitive data:**

- Never commit `.env`, credentials, tokens, LLM API keys, or runtime traces.
- `.env.example` may contain placeholders only.

---

## 3. Comet Routing & Git Workflow

**Git:**

- Work on the currently checked-out branch; do not create, switch, or rename branches unless
  explicitly asked.
- Do not commit unless explicitly asked.
- Run `git status --short` before and after non-trivial edits.

### 3.1 Project config is the source of truth

```yaml
# .comet/config.yaml
schema: comet.project.v1
default_workflow: native      # /comet always forwards here
workflows: [native, classic]
ambient_resume: true
native:
  artifact_root: docs         # docs/comet/
  clarification_mode: sequential
  archive_confirmation: automatic
classic:
  artifact_layout: legacy     # openspec/
  language: en
  review_mode: standard
  auto_transition: true
```

- `/comet` only reads this config and forwards deterministically to `/comet-native`.
  It does NOT pick a workflow from task size. Never re-derive routing in chat.
- `/comet-classic` is the permanent Classic entry and must be typed explicitly.
- `/comet-tweak`, `/comet-hotfix`, `/comet-open`, `/comet-build`, `/comet-verify`,
  `/comet-archive` are Classic-internal phase/preset entries. The Classic router selects them.
  Do not name them in a routing decision; use them only for deliberate manual recovery.

### 3.2 Default: no change

Execute directly and emit one `[NOTE]` line summarising the change. No scoring, no `[ROUTE]`.

### 3.3 HEAVY signals — open a Comet change

Any one of these → open a change instead of editing directly:

- Structural schema / OWL / Neo4j migration
  (NOT plain registry read/write; NOT capability param / display name / description edits)
- Touches > 2 modules AND > 5 files
- Requirements genuinely ambiguous — design exploration needed
- SAP WRITE path (still gated by Human Approval per §2 regardless)

### 3.4 Workflow selection — decided once, at change creation

| Signal profile                                                                                                       | Workflow         | Entry            |
| -------------------------------------------------------------------------------------------------------------------- | ---------------- | ---------------- |
| Structural schema / OWL / Neo4j migration, or any change whose spec delta must be reviewable as an OpenSpec artifact | Classic          | `/comet-classic` |
| Everything else that fired a HEAVY signal                                                                            | Native (default) | `/comet`         |

- A change never migrates between workflows. If the wrong one was chosen, finish or abandon it
  explicitly, then open a new change on the other side.
- Do not run a Native and a Classic change on the same files at the same time.

`[ROUTE]` is an announcement, not a confirmation request — emit it, then enter:

```
[ROUTE] Workflow: {native | classic} | Trigger: {HEAVY signal} | Change: {name | new} | Reason: {one sentence}
```

### 3.5 `[BLOCKED]` — stop and ask before entering any workflow

- Task references an undefined capability or unknown RFC name
- Task would touch the SAP WRITE path without confirmed Human Approval
- Ontology class / property rename or deletion with unclear blast radius
- Scope ambiguous across ≥ 3 modules
- Multiple active changes and the target is unnamed (`comet resume-probe` returns `ask_user`)
- `.comet/config.yaml` is malformed, or the probe returns no `nextCommand`

### 3.6 Resume

- Normal recovery is one step: `/comet`. State is read from disk, not from conversation history.
- **`both` caveat:** the resume probe resolves the configured default workflow and inspects only
  that side. An active **Classic** change will NOT be found by `/comet` or by ambient resume
  while `default_workflow: native`. Re-enter Classic work with `/comet-classic` explicitly.
- `comet status` shows Native and Classic sections separately; use it when routing looks wrong.
  `comet doctor` is for broken installs or damaged state. Neither is a required recovery step.

### 3.7 Clarification

- Native **Shape** owns requirement clarification (`sequential`: one upstream decision per round).
- Classic **Open/Design** owns it on the Classic side.
- Do not run a separate plan-and-wait clarification round in chat before entering a workflow.

### 3.8 Closeout — tiered, NOT per task

- **Per task (no change):** one `[NOTE]` line + only the relevant verification from §4.
- **Per change:** the workflow's own Archive step updates specs and archives. Do not hand-edit
  `.comet.yaml`, `comet-state.yaml`, or archive paths.
  Native follows the configured `archive_confirmation` mode (`automatic` or `required`).
- **Per workstream archive ONLY:** update the runbook + `docs/runbooks/README.md`, update
  roadmap / wiki progress with links.

---

## 4. Verification (run only what the change touches)

Always:

```bash
git status --short
```

Then, by change type:

| Change type                  | Command                                                    |
| ---------------------------- | ---------------------------------------------------------- |
| Schema / registry / ontology | `openspec list --json && openspec validate --all --strict` |
| Frontend                     | `npm --prefix frontend run verify`                         |
| Agent call-plan              | `scripts/verify-agent-callplan-evidence.sh`                |

- Do not run the full suite for edits it doesn't touch.
- Do not claim success without running the relevant command and checking its output.
- **Inside a Native change:** every mandatory acceptance item needs current evidence bound to the
  active snapshot. Record it with `comet native evidence format`; a check that was not actually
  run cannot be written as passed. Failed or stale evidence returns the change to Build.
- **Inside a Classic change:** phase exits are enforced by Comet's Guard scripts. If a phase entry
  check reports a mismatch, follow the script output instead of writing state from the wrong phase.
- `openspec` commands are valid for Classic changes and for the standalone spec store. A Native
  change does not produce OpenSpec artifacts — run the command above as a project verification
  step, not as a Native archive gate.

---

## 5. Communication

- Respond in Chinese unless asked otherwise.
- Use English for code, identifiers, filenames, env vars, and comments.
- State assumptions and success criteria in one line before non-trivial implementation.
- Mention exact file paths changed when updating docs or architecture.

<comet-ambient-resume>
<!-- Managed by Comet. Edits inside this block may be replaced by comet init/update. -->
<!-- Contract: comet.resume_probe.v2 -->

## Comet Ambient Resume

In this repository, before starting work that may need code changes or investigation, pass the current user request to the read-only probe when a Comet workflow may already be active: `comet resume-probe . --stdin --json`.

- If the user explicitly invokes any Comet Skill through the host (for example, `@comet`, `/comet`, `@comet-native`, or `/comet-hotfix`), that explicit invocation takes precedence over this resume protocol; do not run the resume probe, and enter the invoked Skill directly.
- Trust only the returned `workflow`, `skill`, and `entrySource`; project configuration or the no-config compatibility fallback alone selects them. Do not scan or switch to the other workflow.
- If the probe returns `auto_resume`, briefly state the selected active change and enter the permanent entry in `nextCommand`. Do not treat a state command as the resume entry or advance it blindly.
- If the probe returns `ask_user`, ask one short question and wait.
- If the current request did not explicitly invoke a Comet Skill and the probe returns `out_of_scope` or `none`, do not enter the Comet workflow.
- If configuration or state is invalid and `nextCommand` is absent, stop and report the reason; do not guess another workflow.
- Never attach unrelated work merely because an active change exists. The Native entry inspects uncommitted work; the probe does not attribute it automatically.
</comet-ambient-resume>
