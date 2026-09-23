# Jev 决策层引入评估方案（Proposal）

- **状态**: Pending（阻塞：当前无 Jev API Token，待获取后执行离线 shadow eval）
- **创建日期**: 2026-09-23
- **参考文章**: 《从 Palantir 本体论到 Jev 决策模型：构建企业级 AI 智能体的混合架构》（人月聊IT，何明璐，2026-09-23）
- **决策结论**: 不直接集成；先离线评估 → shadow 验证 → 满足全部准入判据后才接入

---

## 1. 背景与定位

项目定位为"基于能力本体建模驱动的 SAP 智能体"。当前在自然语言交互中选择能力（capability）的环节，已形成"确定性规则为主、LLM 在注册闭集上做结构化分类为辅"的机制。

Jev（TypeSafe System One）是非生成式判别小模型，只做判断/分类/聚合，不生成文本。其价值主张是：对"答案空间有限、边界模糊"的判断，以约 200 倍速度、约 400 倍成本替代通用 LLM。

**核心判断**：Jev 在本项目中的目标切片很窄——仅替换当前落到 LLM 的**长尾意译意图分类**流量；不替换确定性规则层，不承担参数抽取，不豁免 WRITE 人工审批。

## 2. 当前能力选择机制（已按代码核实）

入口 `build_intent_adapter(mode)`，三种可切换模式：

| 模式 | 机制 | 未命中/多命中 |
|---|---|---|
| `rule` | `parse_declared`：`triggerKeywords`（退回 `primaryKeywords`）触发；`weakKeywords` 仅参与歧义判断 | 零触发 → REJECT；多触发 → 候选列表；多 weak 无 primary → 歧义 |
| `llm` | system prompt 内联全部注册能力（id + description + inputs），strict JSON 返回 `capabilityId` / `candidates` / `escalation` | 闭集校验丢弃未知 id；多候选 → `ESCALATE_TO_PLANNER`；无法识别 → CLARIFY |
| `hybrid` | 先 LLM，`LlmUnavailable` 时退回 `rule` | LLM 不可用仍可服务 |

配套机制：

- **多轮 sticky 继承**（`resolve_with_context`）：沿用上轮 `capabilityId` 合并槽位，新句出现 primary keyword 才切换能力；
- **闭集防护**：LLM 返回的 `capabilityId` 必须在 `catalog.capability_ids` 内；参数名按能力入参闭集过滤；RFC 名 / OData override 检测；
- **advisory 通道**（`parse_context_candidates`）：LLM 仅在只读能力子集上产出建议信封，定位是证据而非决策。

## 3. Jev 能力概要与约束

| 维度 | 内容 |
|---|---|
| 三个原语 | **Choice**（候选概率分布 + 置信度）/ **Score**（有序档位加权分）/ **Noul**（命题成立概率，非强度） |
| 工程约束 | Choice ≤ 255 选项；state + questions ≈ 32k token；只吃文本（多模态需先转文字）；多问与单问同耗时（单次前向并行） |
| 性能/成本 | 官方称分类任务比通用 LLM 快约 200×、便宜约 400×，单次约 0.3s |
| 关键风险 | **英文优先，CJK 的 R@1 从 61.5% 降至 48.9%**——中文场景必须实测，初始阈值按 0.93 而非 0.9 |

## 4. 目标架构：插入一层，而非替换

```text
用户语句
 → ① rule 关键词触发（确定性，现状不动）
 → ② Jev Choice（候选 = registry 快照）   ← 待评估的新增层
      confidence ≥ 0.93 → 选中，继续走参数抽取 / 缺槽澄清
      confidence < 0.93 → ③ LLM 分类（现状兜底）
 → 闭集校验 / 参数抽取 / WRITE 审批 —— 全部照旧
```

- **本体出题**：Jev 的候选集、描述、别名全部来自 registry 快照；Jev 不产生任何能力名；
- Jev 判断结果（question、state 快照、候选概率、置信度）按现有 `parameterSources` / evidence 同结构记录，保证可追溯；
- Jev 作为 agent 内一个 allowlisted **decision adapter**（治理方式类比 executor bindings），不直读原始数据表、不直连 SAP。

## 5. 不可逾越的边界

1. **WRITE 红线**：Jev 可以"选中" Action 能力，但执行前一律 `awaiting_approval`；任何模型置信度都不能豁免 recorded human confirmation（项目硬边界）；
2. 不替换确定性参数抽取（物料/工厂/公司代码等走 regex + datatype restriction）；
3. 不替换 triggerKeywords 已覆盖的触发路径；
4. 不承担内容生成、叙述、多步规划（LLM 职责）；
5. 控制流、权限、副作用全部留在确定性代码中，模型只填判断；
6. 业务规则留在 registry / validator，不进 prompt，也不变成模型权重中的隐性知识。

## 6. 离线 shadow eval 计划（获取 Token 后执行）

### 6.1 语料选取

- 从现有 `evals/` 各 intent 用例中，挑出**确定性层（`triggered()`）未命中**的句子——即真正会落到 LLM 的意译长尾切片；
- 只在该切片上比较，不用全量意图流量（happy-path 已被确定性层覆盖）。

### 6.2 调用模板

- state：registry 快照序列化文本（每个能力的 id + description + aliases + examples + inputs）；
- question：单个 Choice，"该语句对应哪个已注册能力？"；
- 记录：Top-1/Top-2 候选及概率、整体置信度、延迟。

### 6.3 对比基线

当前 hybrid 路径（LLM 分类）的选择结果与延迟。

### 6.4 评估指标

- 中文切片 Top-1 准确率（对比 LLM 基线）；
- 各置信度区间的实际准确率分布（校准情况）；
- 0.93 阈值以上的流量覆盖率及覆盖内准确率；
- 延迟与成本对比。

### 6.5 准入判据（须全部满足才集成）

1. 中文切片 Top-1 准确率不低于现有 LLM 路径；
2. 0.93 阈值以上覆盖大部分流量，且覆盖内准确率可接受；
3. 已出现或可预见真实的并发 / 成本压力（纯演示规模下此条不成立，方案继续挂起）；
4. 上线前完成一次离线校准评估：扫描不同阈值下的精确率、召回率、误报率及"覆盖率—覆盖内准确率"曲线，禁止拍脑袋定阈值。

### 6.6 上线节奏（评估通过后）

1. shadow 模式：Jev 判断全部记录但不下发，积累真实数据后按业务域定阈值；
2. 按域差异化阈值（如补货场景可放宽，财务付款场景需更严）；
3. 定期用执行结果回溯各区间实际准确率，动态修正阈值；
4. 必要时以中文基座微调，缓解 CJK 准确率下降。

## 7. 后续可选扩展（本次不做）

- **Score**：AR/AP 敞口风险高/中/低分档（`review_customer_exposure` / `review_vendor_exposure`）；
- **Noul**：现有事实证据是否足以形成提案的闸门；补货提案紧急度判断（数量逻辑仍保持确定性）；
- 置信度驱动"渐进式分层介入深度"（低风险一键确认 / 高风险多专家会审），但不改变审批有无。

## 8. 待办

- [ ] 获取 Jev API Token
- [ ] 按 §6 执行离线 shadow eval 并记录结果
- [ ] 根据准入判据决定：集成（按 §4 架构）/ 继续挂起 / 放弃
