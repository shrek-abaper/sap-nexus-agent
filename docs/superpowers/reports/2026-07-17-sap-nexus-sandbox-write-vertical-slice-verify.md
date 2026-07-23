# Verification Report — sap-nexus-sandbox-write-vertical-slice

| Field | Value |
|---|---|
| Change | `sap-nexus-sandbox-write-vertical-slice` |
| Workflow | Comet full |
| Verify mode | full |
| Date | 2026-07-17 |
| Language | zh-CN |
| Result | **PASS** |

## 结论

verify-fail repair 已关闭外部 Human Approval、approval authority、参数快照完整性、单次执行、stateful JCo LUW 与 WRITE trace 回放缺口。feature 分支已 fast-forward 合并到 `main@a0ceef0`，merged-main 自动化验证全部通过；三轮 thorough review 的最终结论为 `Critical=0`、`Important=0`、`Ready to merge: Yes`。Comet archive 随后以 `7/7` 完成，change 已移至 `openspec/changes/archive/2026-07-17-sap-nexus-sandbox-write-vertical-slice/`，主 spec 已合并。

本 repair 全程只运行 mock/unit/build/eval/OpenSpec 验证，**没有再次执行 SAP WRITE**。既有 sandbox live 证据仍为 PR `10137471`，Gateway trace `6d04f0b2-754b-490f-8f7d-5142a6593980`，采购组 `601`。

## 验证总览

| 维度 | 状态 | 证据 |
|---|---|---|
| Completeness | PASS | OpenSpec repair tasks、Design Doc、delta spec、runbook、README、roadmap 已同步 |
| Correctness | PASS | Agent、Gateway、Frontend、三组 eval 与 OpenSpec strict 全部通过 |
| Coherence | PASS | `EXPORTS.NUMBER` primary + `PRITEMEXP.PREQ_NO` fallback；HTTP/trace 同源 ActionResult |
| WRITE safety | PASS | 外部 decision、service token、不可覆盖 approvalId、三方 hash、原子 claim、stateful JCo LUW |
| Audit truth | PASS | `none/committed/rolled_back/rollback_failed` 来自实际事务阶段；post-commit failure 保持 committed |

## CRITICAL 修复闭环

### 1. 外部 Human Approval

- 首次 Action 只返回 `awaiting_approval` + pending ApprovalRecord，zero Gateway approve/execute。
- Workbench approval API 只接受 `{decision}`，continuation 使用服务端保存的 exact CallPlan/validation/ApprovalRecord。
- reject、重复 decision、validation/capability/snapshot mismatch 均不执行 Gateway/SAP；pending failure 不伪造 approved。

### 2. Gateway approval authority 与 immutable snapshot

- `/approve` 要求 `X-SAP-Nexus-Approval-Token`，并校验 capability、approved 状态、当前有效且不超过 600 秒的 TTL、record hash 自洽。
- Agent/Gateway 共享 compact sorted UTF-8 JSON SHA-256 canonicalization。
- Gateway 分别重算 stored parameters 与 actual execute parameters，request hash 只作为额外交叉校验。
- `approvalId` 使用 `putIfAbsent`，executing/executed 不可通过重放 `/approve` 复活。

### 3. 单次执行与 JCo 事务边界

- dispatch 前原子 `approved -> executing`；普通并发与“dispatch 阻塞期间重放 approve”均只有一次 dispatch。
- Action dispatch exception 消费 approval，返回/trace 同源 failure，重放返回 `APPROVAL_DUPLICATE`。
- `BAPI_PR_CREATE` 与 commit/rollback 共享 `JCoContext.begin/end` stateful LUW。
- commit lookup/execute/RETURN failure 在同一 context rollback；rollback failure 显式为 `rollback_failed`。
- commit 成功后的 PR 号提取异常返回 `NORMALIZATION_ERROR + committed`，不伪造 rollback。

### 4. Replay-complete WRITE trace

- Action success、approval 拒绝、参数早期失败、dispatch exception、SAP business error、commit error 均写 `resultSummary`。
- `resultSummary` 包含 `prNumber`、真实 `commitStatus`、SAP RETURN；READ/validate 继续使用空 summary。
- 文本脱敏覆盖 `key=value`、colon、JSON-like、空格分隔、Bearer/Basic、quoted multi-word secret 与 SAP destination/host identity。

## Fresh Evidence

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest agent/tests/ -q` | `233 passed, 1 skipped` |
| `GRADLE_USER_HOME=/tmp/gradle-home /tmp/gradle-8.8/bin/gradle --no-daemon test --rerun-tasks` | `BUILD SUCCESSFUL`；`16 actionable tasks: 16 executed`；JUnit XML `145 tests, 0 failures, 0 errors, 0 skipped` |
| `npm --prefix frontend run verify` | typecheck PASS；Vitest `33/33`；Next production build PASS |
| `scripts/verify-agent-callplan-evidence.sh` | Agent suite PASS；inventory eval `7/7` |
| `.venv/bin/python -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json` | `13/13` |
| `.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json` | `9/9` |
| `openspec validate --all --strict` | `7 passed, 0 failed` |
| `git diff --check` | PASS（无输出） |
| `git merge-base --is-ancestor feature/20260716/sap-nexus-sandbox-write-vertical-slice main` | PASS（exit code 0）；feature 分支随后安全删除 |

首次无 `GRADLE_USER_HOME` 的最终 Gradle 重跑在 sandbox 内因只读 home native cache 报 `libnative-platform.so` 加载失败；切换到可写 `/tmp/gradle-home` 后同一 Gradle 8.8 发行包完整运行并通过。OpenSpec 的 PostHog DNS flush 错误仅影响 telemetry，目标命令 exit code 为 0。

## Thorough Review Disposition

| Round | Finding | Disposition |
|---|---|---|
| 1 | forged approval / actual parameters 未绑定 / duplicate TOCTOU | service token + strict record + canonical hash + atomic claim |
| 1 | WRITE early trace / inferred rollback / pending UI approved | 同源 ActionResult + explicit status + approval state derivation |
| 2 | approval replay / 缺 JCoContext / commit exception / dispatch exception / free-text leak | putIfAbsent + stateful LUW + rollback truth + structured trace + expanded redaction |
| 3 | post-commit extraction truth / Basic & quoted secret / missing tests | `commitSucceeded` + expanded regex + explicit regression tests |
| Final spot-check | Critical / Important | `0 / 0`；Ready to merge: Yes |

## Verify Guard Repair

- merged-main verify guard 首次执行因脚本为 `100644` 而报 `Permission denied`；根因是 `.comet.yaml` 直接执行脚本，但 Git 未保存 executable bit。
- 将 `scripts/verify-agent-callplan-evidence.sh` 持久化为 `100755` 后，直接执行同一入口获得 GREEN：Agent `233 passed, 1 skipped`，eval `7/7、13/13、9/9`，OpenSpec strict `7/7`，exit code 0。
- 本修复仅改变文件 mode。当前会话的 multi-agent 策略不允许未由用户要求的 subagent，因此未派发额外 reviewer；以 Git mode diff、同一 guard 的 RED/GREEN 和完整命令输出复核。

## 最终评估

**PASS — local merge、merged-main verification、主 spec 合并与 Comet archive 均已完成。**
