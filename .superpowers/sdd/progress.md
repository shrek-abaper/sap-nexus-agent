# SDD Progress Ledger - sap-nexus-agent-conversational-context

Plan: docs/superpowers/plans/2026-07-26-sap-nexus-conversational-context.md
Design Doc: docs/superpowers/specs/2026-07-26-sap-nexus-conversational-context-design.md
base-ref: 133f026c52f6d55ec6ed9345395d5b6336fef156
Branch: feature/20260726/sap-nexus-agent-conversational-context
build_mode: subagent-driven-development
tdd_mode: tdd
review_mode: standard

## Completed Tasks

Task 1: complete (commits 9cf1cee..ac56fce, review: implementer self-review + coordinator verify, 5 passed)
- ConversationContext 数据模型: LastContext/Turn/ConversationContext frozen dataclass
- agent/sap_nexus_agent/conversation_context.py + test, camelCase JSON, history tuple↔list
- 纯新增未 touch 现有模块, 向后兼容

Task 2: complete (commit 83099a2, review: implementer self-review + coordinator verify, 709 passed)
- IntentAdapter 签名扩展: Callable[[str, ConversationContext|None], IntentParseResult], 默认 None 向后兼容
- run_query 条件式分发 (context None 时单参, 非 None 时双参)
- 4 concerns 均 observations (合理): brief 断言错误已修正/parse_inventory_intent 必要扩展/条件式分发/_messages 忽略 context(Task4)
- **关键发现**: parse_intent single-intent 路径不设顶层 capability_id (仅 matched_intents[0].capability_id), selector 用 intent fallback
- pre-existing 3 collection errors (scripts 模块路径 + zl-projects editable install) 与本改动无关

Task 3: complete (commit e9c22f2, review: implementer self-review + coordinator verify, 148 passed)
- sticky 延续判定算法 (Q1=覆盖): context.last_context 存在且无主关键词 -> 继承 capability_id, 合并参数, 重判 missing
- rule 路径不调 LLM (hybrid 安全兜底), SELECT 后追问也支持
- 2 concerns: (1) sticky 路径硬编码 contains_rfc_name=False (gateway double-layer 缓解, Task 5 补 defense-in-depth); (2) sticky 返回 intent=None (selector 用 capability_id fallback, Task 5 验证下游)
- 4 brief 缺陷修正 (测试夹具/纯文字, 未改算法语义)

Task 4: complete (commit 14473de, review: task reviewer PASS, 721 passed)
- LLM 路径历史注入权威/不可信分离 (D9): SystemMessage 契约 + <durable_context_data> HumanMessage + closed-set 校验
- 近 3 轮窗口 = history[-6:] (6 Turn, implementer 修正 brief [-3:] bug, Q3 语义正确)
- review: 4 Minor (Turn TYPE_CHECKING导入/_messages 返回类型/hide_from_ui缺失/缺端到端injection测试), 0 Critical/Important, 安全双重防线有效
- Minor 记录待最终审查 triage

Task 5: complete (commits 81d1fe6 + fd863a4, review: implementer self-review + coordinator verify, 161 passed)
- orchestrator/workbench_output 透传 context (Task 2 已实现, 本 task 验证) + outcome lastContext 回填 (序列化派生自 match_decision)
- Task 3 concern 1 补全: sticky 入口前 _detect_rfc_name/_detect_odata_override (defense-in-depth, intent 层早期拦截)
- Task 3 concern 2 验证: sticky intent=None 但 capability_id 非 None, selector 短路, 4 处 .intent 使用不依赖 sticky
- 4 concerns 均 observations (brief 派生方案 vs AgentOutcome 字段, 功能等价)

Task 6: complete (commit 5bb67ec, review: implementer self-review + coordinator verify, 730 passed)
- CLI --context stdin JSON 模式 (仿 --continue-action), 解析 ConversationContext 传 run_query
- 无 --context 时 context=None 向后兼容; 异常 exit 2 + INVALID_CONTEXT_PAYLOAD
- 3 concerns 均 observations (清理旧 report/保留 brief verbatim 未用 import/严格按 brief)

Task 7: complete (commits 9651acd + a1bb758 fix, review: implementer + fix agent, npm verify 全绿 65 tests)
- frontend agent-runtime-adapter.ts: sessions Map<conversationId, SessionState> + context 透传 + Q2 审批 pending 拒绝
- fix concern 1 (Important): Q2 判据改 run 记录 pendingOutcome && !decision (方案 B), 移除 lastRunStatus 死状态
- fix concern 3: history slice(-6) 对齐 Python history[-6:] (近3轮=6Turn)
- concern 2 (observation): runLocalPythonAgent --context 分支无 spawn 级单测 (observable 契约已覆盖)

Task 8+9: complete (commit a4a8d78, review: implementer self-review + coordinator verify, npm verify 全绿 68 tests)
- AgentConsole conversationId 生成/维护 + "新对话"按钮接线 + createConversationId() DRY
- Task 9 (API route 透传 conversationId) 被 Task 8 C1 覆盖: route.ts + agent-runs-route.test.ts
- C1 (scope expansion): 合理 (route 丢弃 conversationId 致透传链断裂, 必须修)
- C2 (observation): AgentConsole 组件交互测试受限于无 jsdom/RTL, 可测部分已 TDD 覆盖, Task 11 E2E 兜底

Task 10: complete (commit c72b754, review: implementer self-review + coordinator verify, 737 passed)
- Python 端到端多轮场景测试: 核心 + 边界 1-6 + 单轮回归 (25 tests)
- **修复真实 bug**: select_capability CLARIFY 分支未携带 capability_id/parameters -> LastContext.capabilityId=null -> sticky 第2轮中断. 修复: capability_id 推导 (parse_result.capability_id -> matched_intents[0] -> INTENT_TO_CAPABILITY[intent]) + 携带 parameters
- 更新 3 个旧测试 (CLARIFY capability_id 旧契约 -> 新契约)
- 前一次 implementer 因配额耗尽中断, retry 接续完成

Task 11: complete (verify all green + e2e)
- 8.1 openspec validate --all --strict: 11 passed
- 8.2 npm --prefix frontend run verify: typecheck + test + build 全绿
- 8.3 scripts/verify-agent-callplan-evidence.sh: 11 passed
- 8.4 e2e: start.sh restart + curl /api/agent-runs
  - turn1 "你能查库存吗" -> CLARIFY (narrative "请提供要查询的物料编号和工厂")
  - turn2 "DEMOA2 在 1000" (同 conversationId) -> SELECT (capability_selected MM.Inventory.GetAvailability -> callplan -> gateway_validate)
  - **用户报的 bug 已修复**: turn2 sticky slot-fill SELECT 而非 REJECT

Task 10: complete (Python 端到端多轮场景测试)
- 核心: turn1 CLARIFY -> turn2 SELECT -> 执行 (run_workbench_query x2, mock gateway)
- 边界1-6 全覆盖 (Design Doc §6 矩阵)
- fix (实现 bug): select_capability CLARIFY 分支未带 capability_id+parameters, 致 LastContext 丢失 capability, turn2 sticky continuation 退化为单轮 -> REJECT; 修复后 CLARIFY 携带 capability_id+parameters, sticky 续接贯通
- 3 个旧 contract 测试 (CLARIFY capability_id is None) 更新为新 contract
- 全量回归 737 passed, 1 skipped

## Notes

- review_mode=standard: 多数 task implementer 自审 + 协调者验收勾选；风险 task（LLM 注入/跨模块集成/审批拒绝）派发 reviewer；最终一次轻量审查
- 统一 LastContext 模型（Q1=覆盖, Q2 审批拒绝, Q3 近3轮）
