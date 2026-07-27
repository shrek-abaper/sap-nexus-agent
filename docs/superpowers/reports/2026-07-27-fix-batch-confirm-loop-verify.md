# 验证报告：fix-batch-confirm-loop（hotfix）

- Date: 2026-07-27
- verify_mode: full（scale：6 tasks、15 files；实际代码改动 2 文件）
- review_mode: off（hotfix 预设）
- Branch: hotfix/20260727/fix-batch-confirm-loop

## 新鲜验证证据（本报告运行）

| 命令 | 结果 |
|------|------|
| `openspec validate --all --strict` | 12 passed, 0 failed |
| `bash scripts/verify-agent-callplan-evidence.sh` | exit 0（pytest + eval + openspec 全绿）|
| `grep -c '^- \[ \]' tasks.md` | 0（6/6 完成）|

## Bug 根因

`_last_context_from_outcome`（`workbench_output.py:66`）对 `status="awaiting_batch_confirm"` 落到 SELECT 分支（`match_decision.decision_type==SELECT`），返回 `LastContext(SELECT, {material, unit})`。用户"确认"后，LLM 拿该 last_context 重新发出 `multi_parameters={plant:[5200,1000]}`，`run_query` 又返回 `awaiting_batch_confirm`，死循环。

## 修复

`_last_context_from_outcome` 在 `awaiting_approval` 早返回之后增加 `awaiting_batch_confirm` 早返回 None（`workbench_output.py:75-80`），清空 session last_context，阻止 LLM 基于过时 material 重新发出多值查询。

## Full 验证 7 项

| # | 检查 | 结果 |
|---|------|------|
| 1 | tasks.md 全部 `[x]` | PASS（6/6）|
| 2 | 实现符合 design.md D1（awaiting_batch_confirm -> None）| PASS |
| 3 | 实现符合 design.md（hotfix 无独立 Design Doc，design.md 即设计）| PASS |
| 4 | delta spec 场景覆盖：`awaiting_batch_confirm clears session last_context` -> `test_awaiting_batch_confirm_no_last_context` | PASS |
| 5 | proposal 目标（止死循环）达成 | PASS |
| 6 | delta spec 与 design.md 无矛盾 | PASS |
| 7 | Design Doc 可定位 | N/A（hotfix 无独立 Design Doc）|

## 代码审查

review_mode=off（hotfix 预设），跳过自动代码审查。修复为 1 行早返回 + 1 个回归测试，TDD RED（lastContext=SELECT dict）-> GREEN（None）验证，全套 438 passed/1 skipped 无回归。

## 已知限制（非阻塞）

本修复仅止住死循环。`continue_batch` 的服务层集成（CLI/workbench 入口 + combinations 跨轮携带）仍缺失，批量查询功能端到端不可用。用户"确认"后 last_context=None -> LLM 无上下文 -> CLARIFY/REJECT（优于死循环）。完整修复留作后续 change。

## Final Assessment

无 CRITICAL，无 WARNING。Bug 根因消除（last_context 不再为 awaiting_batch_confirm 返回 SELECT）。新鲜验证全绿。**Ready for archive**（分支处理后）。
