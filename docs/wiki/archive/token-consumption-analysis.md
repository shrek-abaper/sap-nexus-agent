# Token Consumption Analysis

> Analysis of why runbook 05 change consumed 23.46M tokens and optimization strategies.

## Summary

A modest code change (~1,639 lines of Java, across ~6 new + ~5 modified files) consumed **23.46M tokens** in one session. The code itself is ~5% of total consumption. The remaining 95% comes from **context inflation** — large reference documents, skill files, growing conversation history, and redundant re-reading of the same files.

---

## Why 23.46M Tokens for ~1,639 Lines of Java?

### Root Cause 1: Large Reference Documents Stay in Context

Every session turn includes these permanent residents in the LLM context window:

| File | Bytes | ~Tokens |
|------|-------|---------|
| `technical-architecture.md` | 43,195 | ~10,800 |
| `implementation-roadmap.md` | 46,626 | ~11,700 |
| `05-gateway-execution-contract.md` | 18,271 | ~4,600 |
| 4 OpenSpec spec files | ~28,000 | ~7,000 |
| `AGENTS.md` | 5,279 | ~1,300 |
| Global `CLAUDE.md` | 6,199 | ~1,500 |
| `comet-phase-guard.md` | 7,371 | ~1,800 |
| **Subtotal (per turn)** | **~155,000** | **~39,000** |

At ~40k tokens per turn × ~50 turns = **~2M tokens** just from re-reading the same docs each turn. The architecture doc (43k bytes) and roadmap (47k bytes) are the heaviest — together they contribute ~22k tokens per turn.

### Root Cause 2: Skill Files Are Large

The Comet/OpenSpec skill system loads multi-page SKILL.md files on invocation:

| Skill | Bytes | ~Tokens |
|-------|-------|---------|
| `comet-build/SKILL.md` | 19,099 | ~4,800 |
| `comet/SKILL.md` | 16,094 | ~4,000 |
| `comet-design/SKILL.md` | 11,831 | ~3,000 |
| `comet-verify/SKILL.md` | 12,519 | ~3,100 |
| Other OpenSpec skills (avg) | ~6,000 ea | ~1,500 ea |
| `subagent-dispatch.md` (reference) | 10,462 | ~2,600 |
| `dirty-worktree.md` (reference) | 3,286 | ~800 |

When a skill is loaded, its entire SKILL.md and triggered references enter the context. A full Comet session loads skills 20+ times, totaling ~100k tokens from skill files alone.

### Root Cause 3: Conversation History Accumulation

The single biggest factor. Every turn's output (tool calls, code output, file reads, model reasoning) stays in the conversation window. Across a long session:

- ~50 tool call → result cycles
- Code file reads (Java: ~65k, Python: ~38k, Tests: ~40k)
- Plan/design doc creation (674-line plan + 240-line design doc = ~38k)
- Verification command output (gradle test output, agent test output, etc.)
- This **conversation growth** likely accounts for **30-40% of total tokens** (~7-9M)

### Root Cause 4: Iterative Code Reading

The implementation required reading many Java files repeatedly:
- Each time the agent reads a file, the content enters the context
- Re-reading the same files across different turns adds up
- Estimated: ~25% of total tokens from this source (~6M)

### Root Cause 5: Verification Loop

The session closed with multiple verification runs (gradle tests, agent tests, OpenSpec validation, registry validation). Each verification command triggers its output to be read and analyzed, compounding the context.

---

## Estimated Breakdown

| Component | ~Tokens | % |
|-----------|---------|---|
| Permanent reference docs (per turn) | ~2,000k | 9% |
| Skill file loads | ~2,500k | 11% |
| Plan + design doc creation & reading | ~4,000k | 17% |
| Code reading (Java + Python + tests) | ~6,000k | 26% |
| Code writing (actual output) | ~1,200k | 5% |
| Conversation accumulation (growing context) | ~7,800k | 33% |
| **Total** | **~23,500k** | **100%** |

---

## Optimization Strategies

### Tier 1: High Impact, Low Effort

#### 1. Prune Large Architecture Docs from Default Context
- **Problem**: `technical-architecture.md` (43k) and `implementation-roadmap.md` (47k) are required reading by `AGENTS.md` but are reference material, not working context.
- **Fix**: Replace the full-read requirement with a short summary or TL;DR. Only read full docs when the agent needs to answer an architecture question.
- **Impact**: Save ~22k tokens per turn × 50 turns = **~1.1M tokens**

#### 2. Add `.codex/` and `docs/wiki/` to .gitignore
- **Problem**: The Codex `.codex/` directory (312k bytes) contains all skills, references, and scripts that get loaded into context. Unnecessary for code-writing agents.
- **Fix**: Ensure `.codex/` is in `.gitignore`. Already the case — verify no future commits include it.
- **Impact**: Prevents accidental context bloat from skill data files.

#### 3. Reduce Skill File Size
- **Problem**: `comet-build/SKILL.md` is 19k bytes. Much of it is procedural text that could be externalized to reference files.
- **Fix**: Split skill files — keep only the essential workflow in SKILL.md, move detailed reference material to separate files loaded only when needed.
- **Impact**: Save ~3-4k per skill load × 20 loads = **~80k tokens**

#### 4. Use `git diff` Instead of Full File Reads
- **Problem**: Agent reads full Java files every time to understand current state.
- **Fix**: After initial reading, use `git diff` or targeted `codegraph callers` to find specific code sections instead of re-reading entire files.
- **Impact**: Save ~40k per re-read × 15 re-reads = **~600k tokens**

### Tier 2: Medium Impact, Medium Effort

#### 5. Implement Checkpoint / Summarization
- **Problem**: Conversation history grows unbounded — ~30% of token cost.
- **Fix**: Use Claude Code's goal-driven execution pattern. After completing a milestone (e.g., "design doc done", "core classes done"), explicitly summarize what was accomplished and what remains, then ask the user to start fresh with a refined prompt.
- **Impact**: Save ~7-8M tokens by starting shorter Sessions.

#### 6. Reduce OpenSpec Plan Size
- **Problem**: The implementation plan was 674 lines (~28k bytes ~7k tokens). It gets re-read multiple times.
- **Fix**: Keep plans lean — capture the sequence and key decisions, not full design detail. The Design Doc already captures the design.
- **Impact**: Save ~5k per read × 5 reads = **~25k tokens**

#### 7. Consolidate Verification Commands
- **Problem**: Multiple separate verification commands each produce output that stays in context.
- **Fix**: Create a single `scripts/verify-all.sh` that runs all checks and summarizes results in 5 lines. Parse the summary, not the full build output.
- **Impact**: Reduces verification output tokens by ~80%.

### Tier 3: Architectural Changes

#### 8. Introduce Session Scoping
- **Problem**: The runbook "Prompt To Start The Next Session" asks the agent to load many documents.
- **Fix**: Structure the start prompt to specify *which* documents to read based on the task type:
  - Architecture work → read architecture docs
  - Code change → read relevant code only
  - Don't read everything every session
- **Impact**: Variable but significant.

#### 9. Use CodeGraph Instead of Raw File Reads
- **Problem**: Agent reads full Java files to find specific methods.
- **Fix**: Use CodeGraph's `codegraph_explore` and `codegraph_callers` to get exactly the code needed. This returns only the relevant symbols' source rather than full files.
- **Impact**: 3-5x reduction in code-reading tokens.

#### 10. Shorten Skill Descriptions
- **Problem**: The skill loading system in Codex loads full SKILL.md content. Long descriptions (e.g., 169 lines for `openspec-verify-change`) are wasteful.
- **Fix**: Write concise SKILL.md files. Move examples and edge cases to `reference/` files.
- **Impact**: 30-50% reduction in skill-load tokens.

---

## Summary of Suggested Changes

| # | Strategy | Effort | Token Savings | Priority |
|---|----------|--------|---------------|----------|
| 1 | Replace full architecture doc read with summary | Low | ~1.1M | **Immediate** |
| 2 | Verify .codex/ is gitignored | Low | ~0 (prevents future) | **Check** |
| 3 | Reduce skill file sizes | Medium | ~80k | Medium |
| 4 | Use git diff / targeted reads over full file re-reads | Medium | ~600k | High |
| 5 | Milestone-based summarization | Medium | ~7M | **Highest** |
| 6 | Keep implementation plans lean | Low | ~25k | Low |
| 7 | Consolidate verification scripts | Low | ~200k | Medium |
| 8 | Session scoping for document loading | Medium | Variable | High |
| 9 | Prefer CodeGraph over raw file reads | Medium | ~3-5M | **High** |
| 10 | Shorten skill descriptions | Low | ~100k | Low |

## Recommended First Actions

1. **Highest ROI**: Milestone-based summarization (strategy 5) — the single biggest saver at ~7M tokens
2. **Immediate win**: Add document loading scoping — only load large docs when explicitly needed
3. **Code change**: Prefer CodeGraph for code understanding — reduces code reading by 3-5x
4. **Low effort**: Consolidate verification into a single script with summarized output

---

*Analysis date: 2026-06-28*
*Based on runbook 05 (sap-nexus-gateway-execution-contract) session data.*
