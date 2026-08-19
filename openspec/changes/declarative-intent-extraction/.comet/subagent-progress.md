# Comet coordinator checkpoint - declarative-intent-extraction

- Current plan task: Task 17 (docs/superpowers/plans/2026-08-18-declarative-intent-extraction.md,
  "### Task 17: Optional grounded LLM rephrase for llm/hybrid CLARIFY  (tasks.md 4.2)")
- Mapped OpenSpec task: tasks.md line 30
- Stage: done
- Model used: github-copilot/gpt-5.5 (category: ultrabrain) - implementer and reviewer;
  github-copilot/gpt-5-mini (category: quick) - fix round 1 implementer;
  github-copilot/claude-sonnet-5 (category: unspecified-high) - scoped re-review
- BASE commit: 78114c2
- Implementation commit: 478c360 (initial), 38a1321 (fix round 1), checkoff: cdffdf6
- RED/GREEN evidence: new tests RED then GREEN; 121 passed (108 parity + 13 clarify/rephrase);
  full suite 15 failed/1344 passed/1 skipped (+7 net new over 1337 baseline, zero new
  failures)
- review_mode: standard
- Review stages passed: mandatory per-task reviewer (Task 17 is on the ledger's mandatory
  list) -> 1 Critical (non-dict payload exception leak) + 1 Important (missing adversarial
  test) -> fix round 1 -> scoped re-review ADDRESSED both, no new breakage -> Approved.
- Unresolved reviewer feedback: none
- Current fix round: 1/1 (standard cap reached and cleared)
- Risk-task review already triggered this task: yes (mandatory per ledger, also
  self-reported: cross-module, security-sensitive LLM boundary, public API contract change,
  diff >200 lines - all four hit)

Housekeeping note: fix round 1's subagent accidentally committed ~17 unrelated
`.omo/run-continuation/*.json` OhMyOpenCode tooling artifacts. Coordinator cleaned up in
commit 5caa06e (untracked + added `.omo/` to .gitignore) before checking off this task -
scope-boundary violation caught and resolved, not left in the change's history.

GROUP 4: Tasks 16-17 COMPLETE.

Next: Task 18 (tasks.md 4.3, delete legacy branches in intent.py, remove pr_intent.py, remove
the per-capability seam - engine becomes the ONLY extraction path). This is the ledger's
highest-blast-radius task and is on the MANDATORY per-task reviewer list. No brief exists
yet - must extract via task-brief script. Per the brief's own instruction (ledger preflight
ruling #10): grep required before deleting `parse_inventory_intent` (or equivalent) to
confirm no non-test caller remains.
