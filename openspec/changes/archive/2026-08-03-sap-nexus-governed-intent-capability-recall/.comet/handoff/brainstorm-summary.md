# Brainstorm Summary

- Change: sap-nexus-governed-intent-capability-recall
- Date: 2026-08-03

## 确认的技术方案

### open 阶段 D1-D6（已确认）
- D1: IntentEnvelope 替换 IntentParseResult（BREAKING）
- D2: closed-set recall（lexical+alias+example）+ bounded rerank
- D3: LLM 输出 discard + 结构化原因
- D4: 跨轮 continuation 状态机（SHOW_OPTIONS / ESCALATE）
- D5: rule fallback 产出 IntentEnvelope
- D6: IntentAdapter + select_capability 签名升级（BREAKING）

### design 阶段 DT1-DT5（已确认）
- DT1=C: model_evidence 摘要 + raw_payload_ref（摘要用于回放，原始 payload 可选写入 trace）
- DT2=B: 扩展 registry schema，新增可选 `aliases: []` / `examples: []` 字段
- DT3=A: rerank 参数 fit 判断 = LLM 参数覆盖 required inputs 即算 fit（与 selector missing 判断一致）
- DT4=A: discard 检测在 `_payload_to_envelope` 内部，单一入口
- DT5=A: 扩展 ConversationContext 字段（pending_show_options / pending_escalate），durable 由 P0B 接管

### registry schema 扩展（DT2 修正）
- 现状：3 个 capability 均无 aliases/examples 字段
- 扩展：新增可选 `aliases: list[str]` / `examples: list[str]` 字段
- 影响：`registry/capabilities.yaml` + `registry_loader.py`（CapabilityDescriptor 新增字段）

## 关键取舍与风险

- BREAKING: IntentParseResult / SelectionResult / to_selection_result() 全部移除
- BREAKING: IntentAdapter callable 返回类型变更（全量迁移调用方）
- registry schema 扩展：可选字段，向后兼容
- recall + rerank 在 3 个 capability 下收益小，但为规模扩展预留架构
- 跨轮 ESCALATE 续接 planner 仅 dry-run，不执行 Gateway
- LLM prompt schema 升级可能触发输出格式回归，需扩展 Eval 覆盖 discard 场景

## 测试策略

- TDD 优先级：数据结构 (1.x) → recall (2.x) → rerank (3.x) → discard (4.x) → envelope 产出 (5.x) → selector (6.x) → 跨轮 (7.x) → 调用方迁移 (8.x) → Eval (10.x) → 验证 (11.x)
- 单元测试：test_intent_envelope.py / test_recall.py / test_rerank.py / test_discard.py
- 集成测试：test_capability_selector.py 扩展 recall + rerank 全链路
- 跨轮测试：test_conversation_context.py 扩展 SHOW_OPTIONS / ESCALATE 跨轮
- Eval：evals/matcher_cases.yaml 扩展 11 类场景
- 回归：scripts/verify-agent-callplan-evidence.sh 全量

## Spec Patch

brainstorming 过程中发现 2 个 spec 补充点，将在 Design Doc 创建后回写 delta spec：

1. `governed-intent-envelope-recall` spec 的 "Bounded rerank stage" 需补充 **参数 fit 判断依据**（DT3=A：LLM 参数覆盖 required inputs 即算 fit）
2. `governed-intent-envelope-recall` spec 需补充 **registry schema 扩展**（DT2=B：新增可选 aliases/examples 字段）
3. `conversational-context` spec 需补充 **PendingShowOptions / PendingEscalate 持久化路径**（DT5=A：扩展 ConversationContext 字段，durable 由 P0B 接管）
