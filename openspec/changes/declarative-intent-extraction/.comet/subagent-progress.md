# Comet coordinator checkpoint - declarative-intent-extraction

- Current plan tasks: Tasks 13-15 (docs/superpowers/plans/2026-08-18-declarative-intent-extraction.md,
  batched dispatch per SDD ledger preflight ruling #9)
- Mapped OpenSpec tasks: tasks.md lines 23-25 (3.1, 3.2, 3.3)
- Stage: done
- Model used: github-copilot/gpt-5.5 (category: ultrabrain) - implementer (with one resumed
  continuation to correct an over-conservative BLOCKED call) and batch reviewer
- BASE commit: b282b7c
- Implementation commits: bf2b201 (PR + ordering fix), 25da9e5 (Inventory + capability_id
  nulling fix), d8f29d7 (PO, clean flip). Checkoff: 19a52c8.
- RED/GREEN evidence: parity 108/108 after each capability; full suite 15 failed/1335
  passed/1 skipped exact match to baseline after each capability; 5 call-plan eval files
  individually verified (3 fully green, 2 retain pre-existing baseline failures independently
  reproduced by coordinator with the seam toggled off).
- review_mode: standard
- Review stages passed: batch reviewer dispatched (coordinator judgment - not on the
  mandatory list, but two real production fixes + a hardcoded capability-id check warranted
  it) - Approved, 0 Critical/Important. 1 minor deferred to final review (inline comment).
- Unresolved reviewer feedback: none
- Current fix round: 0/1 (not needed for the review; one BLOCKED->resume cycle occurred at
  the implementer stage, not the review stage, and was resolved via task_id continuation,
  not a formal fix-loop round)
- Risk-task review already triggered this task: yes (coordinator-initiated, not ledger-mandatory)

GROUP 3 (Tasks 13-15) COMPLETE. `_ENGINE_MIGRATED_CAPABILITIES` = all 3 capabilities.

Next: GROUP 4 - Tasks 16-19 (tasks.md 4.1-4.4: CLARIFY template rendering, optional LLM
rephrase, legacy deletion, declaration-only fixture capability proof). No briefs exist yet -
must extract via task-brief script. Ledger's review-dispatch plan requires MANDATORY
per-task reviewers for Tasks 17 and 18 (18 is the legacy-deletion task - highest blast
radius in the whole plan, deletes pr_intent.py and the per-capability seam).
