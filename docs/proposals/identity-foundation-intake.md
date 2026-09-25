# Phase 5 立项输入：Identity Foundation（稳定身份 + 别名/冲突钩子）

- **信号**: HEAVY（新增身份解析能力）
- **用户授权**: 自主完成，不再确认；Jev 除外

## 背景与判断

当前为单一 SAP 系统，无第二数据源；完整跨系统实体合并（MDM 匹配、跨系统编号归并）
无真实对象，属过度设计。本项只交付有独立价值的 **Identity 基础**（文章：
"Identity & Schema — 谁是谁"），跨系统真实合并仍待第二数据源触发。

## 本次范围

1. **稳定身份派生**：对业务对象类型 + 一组 keyedBy 标识符，确定性生成稳定 canonical identity
   （内容派生，同输入恒等，与具体系统编码无关）。
2. **IdentityRegistry**：
   - `resolve(object_type, identifiers)`：返回 canonical identity，并区分"直接命中 / 经已知别名命中 / 新身份"；
   - `register_alias(canonical, identifiers)`：登记别名（外部系统编号等），为未来 MDM 留接口；
   - 冲突检测：同一标识符集合已映射到不同 canonical identity 时报冲突（fail，不静默归并）。
3. 身份与别名映射可由现有 fact-types 的 businessObject/keyedBy 校验键类型合法性。
4. 纯函数式、无网络/SAP 访问；不自动改任何状态。

## 明确不变

- MatchDecision、Gateway、审批、WRITE 迁移链、补货、Impact Analysis 全部不动；
- 不实现跨系统自动匹配/合并（无第二源），只提供别名登记钩子；
- 解析结果不参与授权（resolve/enforce 边界不变）。

## 成功判据

- 全量 agent 测试 + 全部 evals 绿；行为不变；
- canonical identity 确定性可复现；别名解析与冲突检测正确；未知/空标识符按规则 fail closed。
