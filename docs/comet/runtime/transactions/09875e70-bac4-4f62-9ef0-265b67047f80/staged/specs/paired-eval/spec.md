# Paired Evaluation Gate — Target Specification

## 1. Purpose and contract

The paired evaluation gate compares two registry versions — **Parent** and
**Candidate** — by running the identical offline eval suite set against each
and comparing the six Eval SLIs (architecture §10.1):

`capabilityHitRate`, `parameterCompletionRate`, `businessCaliberAccuracy`,
`missingParameterClarificationRate`, `unsafeExecutionBlockRate`,
`narrativeGroundingRate`.

**Gate rule:** for every SLI with a non-zero denominator on both sides,
`candidateRate - parentRate` must be ≥ 0. Any negative delta, or unequal
denominators for a compared SLI, yields **FAIL** (exit code 1). Otherwise
**PASS** (exit code 0).

The gate is fully offline and deterministic: rule-based intent parsing,
FakeGateway fixtures, and the `recorded_llm` cassette for governed-context
cases. No LLM network calls occur.

## 2. CLI

`.venv/bin/python scripts/paired_eval_gate.py [options]`

| Option | Default | Meaning |
|---|---|---|
| `--parent <git-ref>` | `HEAD` | Git revision whose `registry/*.yaml` are the Parent. |
| `--candidate <git-ref>` | working tree | Git revision to materialize, or the live working tree when omitted. |
| `--output-dir <path>` | `runtime/evals/results` | Report output directory. |

Stdout is one summary line:

```text
Paired eval: PASS | parent=<sha> | candidate=<sha|worktree> | slis=<names compared> | report=<relative path>
```

On FAIL, the line begins `Paired eval: FAIL` and includes each regressed SLI
with parent/candidate rates and delta.

## 3. Eval `--metrics` mode

`python -m sap_nexus_agent.eval <case-file> --metrics` prints one JSON object:

```json
{
  "suite": "matcher_cases",
  "cases": [
    {"caseId": "happy-path", "decision": "SELECT", "passed": true}
  ],
  "sli": {"capabilityHitRate": {"passed": 12, "total": 12}}
}
```

- All cases execute; assertion errors mark the case `passed: false` and never
  abort the file. Cases marked `pending` are excluded from all totals.
- The legacy usage (no flag) and `--context-evidence` retain their exact
  current behavior and output.

### 3.1 Decision and SLI classification

| Case shape | Decision | Mapped SLIs |
|---|---|---|
| matcher case `expected.decisionType` | the `decisionType` value | per mapping below |
| legacy case `expected.status` | `SELECT` for `success`, `CLARIFY` for `clarification`, `REJECT` for `failure` | per mapping below |
| seed/bad-case case `expectedDecision` | `expectedDecision` | per mapping below |

| Decision | SLIs |
|---|---|
| `SELECT` | `capabilityHitRate`, `parameterCompletionRate` |
| `SELECT` with `expectedBusinessCaliber` | additionally `businessCaliberAccuracy` |
| `CLARIFY` | `missingParameterClarificationRate` |
| `REJECT` | `unsafeExecutionBlockRate` |

A case adds 1 to `total` and, when it passes, 1 to `passed` of each mapped
SLI. `narrativeGroundingRate` is emitted as `{passed: 0, total: 0}`.

## 4. Registry materialization

- A git ref is materialized into a temporary directory containing only
  `registry/capabilities.yaml`, `registry/semantic-types.yaml`, and
  `registry/executor-bindings.yaml`, extracted via `git show <ref>:<path>`.
  Paths absent at the ref are skipped.
- Parent subprocesses run with `SAP_NEXUS_AGENT_ROOT=<temp root>`; Candidate
  subprocesses use the working tree (default) or an equally materialized ref.
- Temporary roots are removed after the run.

## 5. Report

Written as `paired-eval-<UTC-timestamp>.json` in the output directory:

```json
{
  "schema": "sap-nexus.paired-eval-report.v1",
  "startedAt": "...",
  "completedAt": "...",
  "suites": ["inventory_availability_cases", "..."],
  "suiteSetHash": "<sha256>",
  "parent": {"ref": "HEAD", "commit": "<sha>", "files": {"registry/capabilities.yaml": "<sha256>"}},
  "candidate": {"ref": "worktree", "commit": "<sha>", "files": {"...": "<sha256>"}},
  "sli": {
    "capabilityHitRate": {
      "parent": {"passed": 20, "total": 20, "rate": 1.0},
      "candidate": {"passed": 19, "total": 20, "rate": 0.95},
      "delta": -0.05, "regressed": true
    }
  },
  "decision": "FAIL",
  "regressedSlis": ["capabilityHitRate"]
}
```

The report is the canonical artifact: it binds each side to exact commit and
per-file hashes so the comparison is reproducible.

## 6. Error behavior

- Invalid git ref, missing `evals/` files, or a metrics subprocess exiting
  unexpectedly → driver exits non-zero with the original error surfaced.
- Zero-denominator SLIs are reported but never gate the result; SLI
  denominator mismatch between sides → FAIL.
