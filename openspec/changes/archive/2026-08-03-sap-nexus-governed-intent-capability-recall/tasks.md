## 1. 数据结构

- [ ] 1.1 新增 `IntentGoal` dataclass（frozen）：`goal_text` / `capability_hint` / `parameters` / `missing`
- [ ] 1.2 新增 `IntentEnvelope` dataclass（frozen）：`envelope_id` / `utterance` / `goals` / `user_constraints` / `ambiguities` / `reference_turn_id` / `model_evidence` / `snapshot_id` / `discard_reasons` / `created_by`
- [ ] 1.3 新增 `PendingShowOptions` dataclass（frozen）：`candidates` / `snapshot_id`
- [ ] 1.4 新增 `PendingEscalate` dataclass（frozen）：`handoff` / `snapshot_id`
- [ ] 1.5 扩展 `MatchDecision` 回放字段：`envelope_id` / `recall_candidates` / `rerank_evidence` / `discard_reasons`

## 2. 召回阶段（recall）

- [ ] 2.1 实现 lexical recall：对 `VisibleCapabilitySet` 中 capability name/description 做关键词匹配
- [ ] 2.2 实现 alias recall：对 registry 中 capability aliases 做匹配
- [ ] 2.3 实现 example recall：对 registry 中 capability examples 做匹配
- [ ] 2.4 实现 recall 合并 + 按 `capability_id` 去重；输出 `recall_candidates`

## 3. 有界 rerank 阶段

- [ ] 3.1 实现 rerank 评分：LLM hint (+3) / lexical (+2) / alias (+2) / example (+1) / 参数 fit (+1)
- [ ] 3.2 实现稳定 tie-break：同分按 `capability_id` 字典序
- [ ] 3.3 输出 `ranked_candidates` + `rerank_evidence`（每个候选的评分明细）

## 4. LLM 输出 discard + 结构化原因

- [ ] 4.1 检测 LLM payload 中未知 capability（不在 `VisibleCapabilitySet`）；丢弃并记录 `"unknown_capability:<id>"`
- [ ] 4.2 检测技术字段（`baseUrl` / `rfcName` / `credential` 等）；丢弃并记录 `"technical_field:<name>"`
- [ ] 4.3 检测非法参数（`__proto__` 等）；丢弃并记录 `"invalid_param:<name>"`
- [ ] 4.4 填充 `IntentEnvelope.discard_reasons`（LLM 输出完全合法时为空）

## 5. IntentEnvelope 产出

- [ ] 5.1 升级 LLM prompt schema：输出 JSON 含 `goals` / `candidates` / `constraints` / `ambiguities` / `evidence`
- [ ] 5.2 实现 `_payload_to_envelope`（替换 `_payload_to_parse_result`）：LLM payload → `IntentEnvelope`
- [ ] 5.3 从 `GovernedContext` 绑定 `snapshot_id` 到 `IntentEnvelope`
- [ ] 5.4 实现 rule fallback 路径产出 `IntentEnvelope`（`created_by="rule"`，`model_evidence` 为空）
- [ ] 5.5 升级 `IntentAdapter` callable 签名：返回 `IntentEnvelope`（BREAKING）

## 6. selector 升级

- [ ] 6.1 升级 `select_capability` 签名：消费 `IntentEnvelope` + `recall_candidates` + `rerank_evidence`（BREAKING）
- [ ] 6.2 在 deterministic matcher 之前接入 recall + rerank 阶段
- [ ] 6.3 填充 `MatchDecision` 回放字段（`envelope_id` / `recall_candidates` / `rerank_evidence` / `discard_reasons`）
- [ ] 6.4 新增 `REJECT(VISIBILITY_DENIED)`：LLM 候选不在 `VisibleCapabilitySet` 时
- [ ] 6.5 移除 `SelectionResult` + `to_selection_result()` compat 桥（BREAKING）

## 7. 跨轮 continuation

- [ ] 7.1 扩展 `ConversationContext`：新增 `pending_show_options` / `pending_escalate` 字段
- [ ] 7.2 实现互斥：写入新 pending 状态时清除已有 pending 状态
- [ ] 7.3 实现 SHOW_OPTIONS 跨轮：Turn N 写 `PendingShowOptions`，Turn N+1 选择清除 + SELECT
- [ ] 7.4 实现 ESCALATE 跨轮：Turn N 写 `PendingEscalate`，Turn N+1 确认清除 + planner handoff（仅 dry-run）
- [ ] 7.5 实现新意图丢弃：Turn N+1 含新 primary keyword 时清除所有 pending 状态

## 8. 调用方迁移

- [ ] 8.1 迁移 `orchestrator.py`：消费 `IntentEnvelope` + 新 `MatchDecision` 回放字段
- [ ] 8.2 迁移 `cli.py`：产出 `IntentEnvelope`（rule + LLM 路径）
- [ ] 8.3 迁移 `llm_intent.py`：`parse_with_llm` / `parse_with_hybrid` / `build_intent_adapter` 返回 `IntentEnvelope`
- [ ] 8.4 移除 `IntentParseResult` 及所有引用（BREAKING）
- [ ] 8.5 验证无残留 `IntentParseResult` / `SelectionResult` import

## 9. 测试

- [ ] 9.1 更新 `test_llm_intent.py`：断言 `IntentEnvelope` shape / `discard_reasons` / `created_by` / `snapshot_id`
- [ ] 9.2 更新 `test_match_decision.py`：断言 5 种 decision type 的回放字段
- [ ] 9.3 更新 `test_capability_selector.py`：断言 recall + rerank 集成 / `VISIBILITY_DENIED` REJECT
- [ ] 9.4 更新 `test_intent.py`：断言 rule fallback 产出 `IntentEnvelope`
- [ ] 9.5 新增跨轮 SHOW_OPTIONS 测试（Turn N 写入 / Turn N+1 选择 / Turn N+1 新意图丢弃）
- [ ] 9.6 新增跨轮 ESCALATE 测试（Turn N 写入 / Turn N+1 确认 / Turn N+1 新意图丢弃）
- [ ] 9.7 新增互斥测试（CLARIFY ↔ SHOW_OPTIONS ↔ ESCALATE）
- [ ] 9.8 新增 discard reason 测试（未知 capability / 技术字段 / 非法参数 / 合法时为空）

## 10. Eval 扩展

- [ ] 10.1 新增 eval case：单能力 SELECT（goal count = 1）
- [ ] 10.2 新增 eval case：多目标 ESCALATE_TO_PLANNER（goal count >= 2）
- [ ] 10.3 新增 eval case：歧义 SHOW_OPTIONS
- [ ] 10.4 新增 eval case：能力缺口 REJECT（未知 capability）
- [ ] 10.5 新增 eval case：技术覆盖 REJECT（OData / 技术字段）
- [ ] 10.6 新增 eval case：越权 REJECT（不可见 capability）
- [ ] 10.7 新增 eval case：跨轮 CLARIFY（已有，确保兼容）
- [ ] 10.8 新增 eval case：跨轮 SHOW_OPTIONS（新）
- [ ] 10.9 新增 eval case：跨轮 ESCALATE（新）
- [ ] 10.10 新增 eval case：LLM 不可用 rule fallback（行为可解释，不扩大执行能力）
- [ ] 10.11 新增 eval case：decision 回放（envelope_id / recall / rerank / discard reasons 可追溯）

## 11. 验证

- [ ] 11.1 运行 `.venv/bin/python -m pytest agent/tests -q`（全量通过）
- [ ] 11.2 运行 `.venv/bin/python -m sap_nexus_agent.eval evals/matcher_cases.yaml`（全量通过）
- [ ] 11.3 运行 `scripts/verify-agent-callplan-evidence.sh`（exit 0）
- [ ] 11.4 运行 `openspec validate --all --strict`（全量通过）
- [ ] 11.5 运行 `npm --prefix frontend run verify`（若触及 frontend）
- [ ] 11.6 编写 verify report：`docs/superpowers/reports/2026-08-03-sap-nexus-governed-intent-capability-recall-verify.md`
