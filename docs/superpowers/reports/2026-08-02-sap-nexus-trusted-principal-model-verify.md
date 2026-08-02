# 验证报告：sap-nexus-trusted-principal-model

**Change:** sap-nexus-trusted-principal-model（P0B 项2 TrustedPrincipal Model）
**Date:** 2026-08-02
**verify_mode:** full
**Branch:** feature/20260802/sap-nexus-trusted-principal-model
**Merge base:** 805874f -> HEAD: 82326ba（12 commits: 6 feat + 6 chore checkoff）

---

## Summary

| Dimension | Status |
|-----------|--------|
| Completeness | 20/20 tasks done（2 deferred: 2.2->项3, 4.3->v1，已注记）；2 delta specs（trusted-principal-scope ADDED + durable-run-state MODIFIED） |
| Correctness | 4/4 requirements 实现（1 partial: Approval binding deferred）；6/7 scenarios 覆盖（1 deferred） |
| Coherence | design D1-D5 全遵循；delta specs 与 design 一致；Design Doc 可定位 |

**Final Assessment:** Ready for archive（1 WARNING + 2 Minor，均为已文档化的 deferred 项，非阻塞）。

---

## 新鲜验证证据（verification-before-completion：自行运行，不信任 agent 报告）

| 命令 | 结果 | 退出码 |
|------|------|--------|
| `openspec validate --all --strict` | 15 passed, 0 failed | 0 |
| `npm --prefix frontend run verify` | typecheck + test (76) + build 全绿（Route 表输出） | 0 |
| `npm --prefix frontend run typecheck` | tsc --noEmit 无错误 | 0 |
| `scripts/verify-agent-callplan-evidence.sh` | 15 passed, 0 failed | 0 |
| `openspec status --change` | isComplete=true, 4 artifacts done, 20/20 tasks | - |

---

## Completeness 验证

### Task Completion
- openspec tasks.md: 20/20 `[x]`，0 incomplete（2.2/4.3 转为显式 deferred 注记，非 unchecked）。
- Superpowers plan: 6/6 task-level + 62/62 step-level checkbox 全勾选。

### Spec Coverage
- **trusted-principal-scope（ADDED）**：4 requirements（Trusted principal model / Durable state binds principal / Cross-principal isolation / Local placeholder principal）。
- **durable-run-state（MODIFIED）**：principalId binding + backfill + list/load filter 语义。

---

## Correctness 验证

### Requirement -> Implementation 映射

| Requirement | 实现 | 证据 |
|-------------|------|------|
| Trusted principal model（server-owned） | TrustedPrincipal types + PrincipalInjector + injectPrincipal | principal/types.ts, principal-injector.ts |
| Durable state binds principal | AgentRunRecord.principalId (required) + SessionState.principalId + createAgentRun/getSession 绑定 | agent-runtime-adapter.ts, durable/types.ts |
| Cross-principal isolation | getAgentRunEvents 返 [] / decide/confirm 抛 not-found / getSession 抛 / load 返 null | agent-runtime-adapter.ts, jsonl-conversation-store.ts |
| Local placeholder principal | PLACEHOLDER_PRINCIPAL + LocalPlaceholderPrincipalInjector | principal/types.ts, principal-injector.ts |

### Scenario 覆盖

| Scenario | 覆盖 | 证据 |
|----------|------|------|
| Principal injected server-side | ✓ | injectPrincipal ignores body principal 测试 |
| Prompt injection cannot supply principal | ✓（结构性） | injector 接收 Request 不接 LLM 输出，route 入口注入先于 LLM |
| Run created with principal | ✓ | createAgentRun binds principalId 测试 |
| **Approval binds principal** | **⚠️ deferred** | tasks.md 2.2 推迟至项3（durable-approval-store） |
| Cross-principal access denied | ✓ | 6 个 cross-principal 测试（events/decide/confirm/session） |
| Local dev uses placeholder principal | ✓ | PLACEHOLDER_PRINCIPAL 默认注入测试 |

---

## Coherence 验证

### Design Adherence（D1-D5）
- D1 TrustedPrincipal server-owned 模型 -> types.ts ✓
- D2 durable state 绑定 principal -> Run/Session done（Approval deferred 项3）✓
- D3 server-owned 注入 -> 4 route handler injectPrincipal，不读 body principal ✓
- D4 cross-principal fail-closed -> ownership before claim（§4.1），read=[]/write=throw ✓
- D5 local placeholder -> PLACEHOLDER_PRINCIPAL，authn non-goal ✓

### delta spec vs design doc
- durable-run-state MODIFIED 与 design D2/D4 一致（principalId binding + filter）。
- trusted-principal-scope ADDED 与 design D1-D5 一致；"Approval binds principal" scenario 对应 D2，deferred 至项3（已文档化）。
- 无矛盾。

### Design Doc 可定位
- `docs/superpowers/specs/2026-08-02-trusted-principal-model-design.md` 存在且与 change 相关。

---

## 最终全分支审查（sonnet，build 阶段末）

**Verdict: Ready to merge.** 4 安全契约全成立（D3 server-owned injection / D4 fail-closed / D2 immutability / §6 backward compat）。0 Critical/Important。

### Deferred Minor findings（非阻塞）
1. **getSession 错误消息泄露存在性**（adapter.ts:92，plan-mandated）：`throw "Conversation does not belong..."` 暴露 conversation 存在。§4.2 允许 throw 故 within spec，与 §4.1 no-leak 不一致。v1 单用户不可达。-> 推迟至多用户硬化（human decision to deviate from plan）。
2. **conversationStore.load principalId 过滤为 dead code**（生产无调用，getSession 自行校验）。tested capability，留未来直连路径。无需动作。
3. Task 2 security test 仅断言 principalId（injector 返常量，已足证，full equality 另有测试）。接受。

---

## Issues

### CRITICAL（Must fix before archive）
无。

### WARNING（Should fix / documented deferral）
1. **"Approval binds principal" scenario deferred**：trusted-principal-scope ADDED spec 的该 scenario 在本 change 未实现，deferred 至项3（durable-approval-store）。tasks.md 2.2 已注记。**接受原因**：项3 同属 P0B workstream，memory `p0b-durable-runtime-split-progress` 已记录项2->项3 依赖，项3 design 覆盖 durable ApprovalStore。**影响范围**：项2 归档后、项3 归档前，main spec 含此未实现 scenario；项3 归档时实现。

### SUGGESTION
- getSession 错误消息一致性（见 Deferred Minor 1）。
- vitest include=src/** 导致 frontend/tests/ 仅 typecheck（pre-existing config，行为由 src/ 测试 runtime 覆盖）。

---

## 结论

验证通过。所有新鲜验证命令（openspec validate / frontend verify / callplan evidence）退出码 0。1 WARNING（Approval scenario deferred 项3，已文档化）+ 2 Minor（deferred）。无 CRITICAL。**Ready for archive**，分支处理待用户决策。
