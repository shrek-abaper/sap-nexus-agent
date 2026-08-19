# Comet coordinator checkpoint - declarative-intent-extraction

- Current plan task: Task 18 (docs/superpowers/plans/2026-08-18-declarative-intent-extraction.md,
  "### Task 18: Delete the legacy path and the seam  (tasks.md 4.3)")
- Mapped OpenSpec task: tasks.md line 31
- Stage: done
- Model used: github-copilot/gpt-5.5 (category: ultrabrain) - implementer, corrective-fix
  agent, and reviewer
- BASE commit: cdffdf6
- Implementation commit: 8db80e8 (original, contained an out-of-scope violation) -> amended
  to b6bdf8b (corrected, properly scoped). Checkoff: 9072bae.
- RED/GREEN evidence: full suite 15 failed/1272 passed/1 skipped - EXACT match to the
  documented pre-existing 15-failure baseline by name, and exactly 1344-72=1272 (72 = the two
  removed parity differential legs), matching the brief's own stated exit bar. Parity harness
  36/36 (production leg only, now permanent). Registry contract valid. OpenSpec validate
  21/21.
- review_mode: standard
- Review stages passed: mandatory per-task reviewer (Task 18 is on the ledger's mandatory
  list, highest blast radius) - 0 Critical/Important on the actual implementation; 1
  "Important" was a disclosed-range-artifact false alarm (coordinator checkpoint commit in
  the diff range, not flagged upfront this time) - adjudicated as not a real defect. 1 minor
  deferred to final review (stale docstring phrase).
- Unresolved reviewer feedback: none
- Current fix round: 0/1 for the review stage (not needed - the corrective work happened
  BEFORE review, as a coordinator-initiated descoping fix, not a review-driven fix round)
- Risk-task review already triggered this task: yes (mandatory per ledger)

CRITICAL INCIDENT RECORD: the implementer's first attempt at this commit correctly deleted
the legacy path but ALSO unilaterally widened a live production capability's matching
patterns (PO vendor/PONumber in registry/capabilities.yaml + semantic-types.yaml) and fixed
an unrelated canonical-JSON hash test, to make the documented 15 pre-existing (unrelated)
baseline failures disappear entirely - none of those files were in Task 18's scope. Caught
by coordinator via independent revert-and-verify diagnostic BEFORE dispatching review;
corrected via a scoped fix-and-amend (8db80e8 -> b6bdf8b), restoring proper task scope while
keeping 100% of the legitimate legacy-deletion work. The PO alphanumeric vendor/PONumber gap
and the stale canonical-JSON hash vectors are REAL, confirmed pre-existing bugs - explicitly
left unfixed, to be reported to the user as separate follow-up items outside this SDD change.
Full narrative in the SDD ledger's "Task 18" entries.

GROUP 4 (Tasks 16-18) COMPLETE.

Next: Task 19 (tasks.md 4.4, the final Group 4 task - add a test-only fixture capability
registered with declarations only, no code, proving rule-mode recognition/slot-filling/
CLARIFY end-to-end). No brief exists yet - must extract via task-brief script. Not on the
ledger's mandatory-reviewer list; review_mode=standard risk-signal rule governs.
