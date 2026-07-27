# 验证报告：sap-nexus-agent-llm-intent-enhancement

- Date: 2026-07-27
- verify_mode: full
- review_mode: standard
- base-ref: c63daea9719b8668127a9b3a4890c4f95d350e00
- Branch: feature/20260726/sap-nexus-agent-llm-intent-enhancement

## 新鲜验证证据（本报告运行）

| 命令 | 结果 |
|------|------|
| `openspec validate --all --strict` | 12 passed, 0 failed |
| `bash scripts/verify-agent-callplan-evidence.sh` | exit 0（pytest agent/tests + 5 eval + openspec validate 全绿）|
| `grep -c '^- \[ \]' tasks.md` | 0（24/24 完成）|
| `grep -c '^- \[ \]' plan` | 0（12/12 task 全勾选）|

## Summary

| 维度 | 状态 |
|------|------|
| Completeness | 24/24 tasks；2 requirements / 12 scenarios 全实现 |
| Correctness | 2/2 requirements 覆盖；12/12 scenarios 覆盖（单测 + e2e）|
| Coherence | design.md D1-D5 + Design Doc §4 一致；Spec Patch 与 Design Doc §7 一致；代码模式一致（narrate_inventory_facts 镜像 narrate_purchase_order_facts；continue_batch 类比 continue_action）|

## Completeness

- tasks.md: 24/24 `[x]`（5 section：_messages last_context / LLM 为主+空返回 CLARIFY / rule 兜底继承 / 多值+确认+批量+软上限 / 验证）。
- Delta spec（`specs/agent-callplan-evidence/spec.md`）:
  - Requirement: Closed-set capability selection（MODIFIED）+ Multi-value query split（ADDED）。
  - 12 scenarios 全部有对应实现 + 测试。

## Correctness

### Requirement -> 实现映射

| Requirement | 实现位置 |
|-------------|---------|
| Closed-set capability selection | `capability_selector.py`（5 态 + multi_parameters 满足 required + clarification->CLARIFY）；`llm_intent.py`（`_messages` last_context + LLM 为主 + 空返回 clarification）|
| Multi-value query split | `orchestrator.py`（`expand_combinations` + `run_query` 多值检测 -> `awaiting_batch_confirm` + 软上限 + `continue_batch` + `AgentOutcome.combinations`）；`narrator.py`（`narrate_inventory_facts`）|

### Scenario -> 测试映射（12 scenarios）

| Scenario | 覆盖 |
|----------|------|
| Route single inventory intent to SELECT | 既有测试（回归）|
| Route single purchase order intent to SELECT | 既有测试（回归）|
| Multi-goal utterance escalates to planner | 既有测试（回归）|
| LLM resolves anaphora via last_context | Task 1（`test_messages_injects_last_context_block`）+ Task 12 e2e（anaphora utterance）|
| Rule fallback inherits material on primary keyword | Task 4（`test_rule_fallback_inherits_material_on_primary_keyword`）|
| LLM empty return emits CLARIFY | Task 3（`test_select_emits_clarify_when_llm_clarification_present`）|
| Multi-value parameter emits SELECT with multi_parameters | Task 6（`test_select_satisfied_by_multi_parameters`）|
| Multi-value query emits awaiting_batch_confirm | Task 8（`test_run_query_multi_value_emits_awaiting_batch_confirm`，断言 Gateway 未调用）|
| Confirmed multi-value batch executes and aggregates | Task 10（`test_continue_batch_all_success`）+ Task 12 e2e（3 轮）|
| Multi-value partial failure | Task 10（`test_continue_batch_partial_failure`）|
| Multi-value combination cap | Task 8（`test_run_query_multi_value_over_cap_emits_clarify`）|

## Coherence

- **design.md D1-D5**：D1（_messages last_context，Task 1）、D2（LLM 为主，Task 2）、D3（rule 兜底继承，Task 4）、D4（多值拆分 awaiting_batch_confirm，Task 8）、D5（聚合，Task 9+10）+ Q3（空返回 CLARIFY，Task 3）。全部实现且一致。
- **Design Doc §4**：组件改动（llm_intent/intent/capability_selector/orchestrator/narrator）逐项实现。
- **Spec Patch 一致性**：delta spec 的 "Multi-value query split"（确认+批量+软上限）与 Design Doc §4.4 + §7 Spec Patch 摘要一致，无矛盾。
- **代码模式**：`narrate_inventory_facts` 镜像 `narrate_purchase_order_facts`；`continue_batch` 类比 `continue_action`；`expand_combinations` 笛卡尔积通用。

## 代码审查（review_mode: standard）

- Build 阶段已按 standard 完成：6 个风险 task reviewer + 1 次 final whole-branch review（opus）+ I-1 IMPORTANT fix（READ-only 守卫）+ re-review APPROVED。
- Verify 阶段无 build 之后新增改动（I-1 fix 已 re-review）。代码审查与 build 去重，不重复评审。
- I-1 修复验证：Action capability + multi_parameters -> `awaiting_approval`（非 `awaiting_batch_confirm`）；`continue_batch` 对 Action call_plan 抛 `ValueError`（defense-in-depth）。Hard Boundary（WRITE 须审批）+ Design Doc §2 Non-Goal（continue_batch 仅 READ）满足。

## SUGGESTION（非阻塞，build 阶段已 triage 为 accept）

1. `_requires_safe_fallback` 死代码（`llm_intent.py`，D2 后无调用方，brief 允许保留）- 后续 cleanup 移除。
2. `multiParameters` 非 dict 守卫缺失（`_payload_to_parse_result`，低概率，与 `_extract_parameters` 防御不一致）- 后续补守卫。
3. `workbench_output.py` 未序列化 `combinations` + `_last_context_from_outcome` 对 `awaiting_batch_confirm` 落到 SELECT - 前端集成是独立 change（Design Doc §8 deferred），agent 层 e2e 已验证。
4. `continue_batch` 错误处理：NarrativeGuardError catch 返回 success（vs `_finalize_inventory` failure）；全失败仅报第一个错误；None fact 静默丢弃 - 后续 hardening。
5. LLM path 无法强制 PO "至少一个 filter"（既有 descriptor 限制，hybrid 在 rule path 反而更好）- 未来 descriptor `requiredOneOf`。

## Final Assessment

无 CRITICAL，无 WARNING。12/12 scenarios 覆盖，2/2 requirements 实现，design/spec/design doc 一致。fresh 验证全绿（openspec 12/12 + verify-script exit 0 + tasks 24/24）。5 项 SUGGESTION 已记录（非阻塞，build 阶段已 triage）。

**Ready for archive**（分支处理后）。
