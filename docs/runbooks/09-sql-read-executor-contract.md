# SQL_READ Executor Contract Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `09-sql-read-executor-contract` |
| Version | `v0.2.0` |
| Status | `Reserved` |
| Created | `2026-06-27` |
| Updated | `2026-06-28` |
| Workstream | Controlled registered SQL read binding, SQL artifact governance, and Registered SQL Read Gateway boundaries |
| Related Change | `sap-nexus-sql-read-executor-contract` |
| Current Phase | Reserved; do not start before Eval seed, second SAP read, and sandbox write pilot |

---

## 1. Session Goal

This runbook is now reserved. `SQL_READ` remains a controlled executor binding boundary for registered, reviewed, parameterized, read-only SQL artifacts, but it is not a near-term runtime priority.

Target product path:

```text
User utterance
-> Capability Matching
-> MatchDecision
-> CallPlan
-> capabilityId
-> executorBinding.type = SQL_READ
-> bindingId
-> registered sqlRef + sqlHash
-> Registered SQL Read Gateway
-> read-only dataSourceRef / governed view
-> TechnicalExecutionResult
-> ExecutionResult
-> ReasoningFact
-> Audit / Replay
```

This workstream must not start until the near-term pilots finish: Eval Harness seed cases, a second SAP read capability, and a sandbox write vertical slice. It does not implement SQL runtime Gateway unless a later pilot explicitly opens that scope.

---

## 2. Source Of Truth

Read these before opening or implementing the change:

```text
AGENTS.md
docs/runbooks/README.md
docs/runbooks/09-sql-read-executor-contract.md
docs/wiki/sap-nexus-agent-technical-architecture.md
docs/wiki/sap-nexus-agent-implementation-roadmap.md
docs/wiki/sap-nexus-agent-technology-selection.md
openspec/specs/capability-registry-gateway/spec.md
openspec/specs/agent-callplan-evidence/spec.md
openspec/specs/registry-ontology-contract/spec.md
registry/README.md
registry/capabilities.yaml
registry/executor-bindings.yaml
```

Expected baseline:

- `SQL_READ` is a reserved executor binding, not part of the near-term runtime roadmap.
- Agent / LLM / user input must never generate, submit, or override SQL.
- Gateway remains a generic technical execution boundary and must not absorb business semantics.
- Capability semantics stay in Registry; technical SQL details stay in executor binding catalog / SQL artifacts.

---

## 3. Proposed Scope

Reserved boundary scope:

- Define `executorBinding.type = SQL_READ`.
- Define binding fields: `dataSourceRef`, `dialect`, `sqlRef`, `sqlHash`, parameters, outputs, limits, and security policy.
- Define SQL artifact lifecycle: review, hash verification, output contract, eval linkage, sensitivity classification, and rollback.
- Preserve Registered SQL Read Gateway contract direction: accepts only `bindingId` and named parameters.
- Define result normalization into `TechnicalExecutionResult`, `ExecutionResult`, and `ReasoningFact`.
- Define negative cases for raw SQL, SQL fragment, table override, schema override, datasource override, connection string, DDL, DML, stored procedure, and side-effect function rejection.

Out of near-term scope:

- Agent-generated SQL.
- LLM-generated SQL.
- User-submitted SQL.
- Arbitrary query endpoint or SQL IDE.
- DDL, DML, stored procedure, side-effect function, or write SQL.
- Direct SAP production database querying as a default path.
- SQL runtime Gateway implementation unless explicitly opened after Eval seed, second SAP read, and sandbox write pilot.

---

## 4. Safety Boundaries

Mandatory rules:

- `SQL_READ` only executes allowlisted `bindingId -> sqlRef` mappings.
- SQL artifacts must be reviewed and versioned before registration.
- Runtime must verify `sqlHash` before execution.
- Runtime must bind named parameters through the database driver, never concatenate strings.
- Data source credentials live outside Registry and trace; Registry stores only `dataSourceRef`.
- Connections, users, and transactions must be read-only.
- Queries must have timeout, maxRows, maxBytes, and rate limits.
- Output schema and evidence roles must be declared before facts reach reasoning.
- Trace must redact secrets and sensitive values.

Forbidden request-owned fields:

```text
sql
sqlText
sqlFragment
tableName
schemaName
dataSourceRef override
connectionString
storedProcedure
functionCall
rawWhereClause
rawOrderBy
```

---

## 5. Acceptance Criteria

| Area | Acceptance |
|---|---|
| Closed execution | Gateway accepts only `bindingId` and declared named parameters |
| No generation | Agent / LLM / user cannot submit SQL or SQL fragments |
| Artifact integrity | `sqlRef` and `sqlHash` are required and verified |
| Read-only guard | Account, transaction, SQL policy, and binding governance are read-only |
| Resource guard | timeout, maxRows, maxBytes, and rate limit are mandatory |
| Output contract | Output columns and evidence roles are declared and validated |
| Audit | trace records capabilityId, bindingId, sqlRef, sqlHash, parameter summary, row count, duration, and redaction status |
| Negative tests | raw SQL, table override, schema override, datasource override, DDL, DML, stored procedure, and side-effect function attempts fail closed |

Recommended verification after implementation:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
# plus future SQL_READ contract tests/evals documented by the change
```
