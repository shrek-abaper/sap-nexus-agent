# SAP Nexus Agent 语义模型

- **版本**: v1（2026-09-23）
- **目的**: 显式定义本项目"能力本体"的分层语义模型、各层载体与链接方式，消除"名为经典本体、实为能力目录"的名实错位。

---

## 1. 核心定位

本项目的语义体系**不是一张全量企业本体大图**，而是一个以能力调用为中心、分层组织的语义模型：

- **YAML 是工作语义**——Agent、Gateway、eval 运行时实际加载和强制执行的事实源；
- **OWL 是离线语义镜像 / 命名锚点**——提供稳定标识与公理镜像，运行时不加载任何 OWL 推理机；
- **契约 validator 是强制门禁**——结构不变量由代码确定性校验，OWL 公理不承担强制职责。

这一选择遵循"以决策为中心、最小必要、嵌入而非侵入"的原则：先让机器在能力选择与参数绑定上"懂业务"，不预先建模无人消费的概念。

## 2. 四层语义模型

```text
④ 事理治理层  规则 / 约束 / 审批策略 / 数据分级        validator + governance
③ 能力行动层  Capability（Function / Action）          registry/capabilities.yaml
② 事实层      Fact Type（键、谓词、字段、证据角色）     ontology/fact-types.yaml
① 术语层      标量语义类型 / 别名 / 抽取词表            semanticType 闭集 + semantic-types.yaml
```

### ① 术语层（Terminology）

回答"业务值用什么语义概念表达"。

- **标量语义类型**（`sapnexus:*`）：BAPI/OData 参数直接携带的值的语义限定，如 `Plant`、`CompanyCode`、`MaterialNumber`、`Amount`、`Currency`、`Quantity`。它们是**派生数据类型**（string/decimal/date 上的模式与长度约束），不是业务对象类；
- **术语别名**：能力的中文 `aliases`、俗名、触发词，是 SKOS 受控词表的雏形；
- **抽取词表**：`registry/semantic-types.yaml` 是"如何从用户文本识别值"的 matcher 目录，经单向 `extracts` 映射到语义类型；
- 载体：capability `inputs/outputs.semanticType` 构成闭集；`ontology/fact-types.yaml` 的 `valueTypes` 是只在 Fact 内部出现的值类型的第二声明通道。

### ② 事实层（Fact）

回答"业务真实状态如何被结构化断言"。

- 每个 Fact Type 声明：`keyedBy`（身份键）、`predicate`（谓词）、`fields`（字段级 semanticType/cardinality/optional）、`evidenceRole`；
- Fact 是能力输出的**证据契约**：`evidenceRole=primaryFact` 的输出必须引用一个 `factTypeRef`；
- 形态区分：单值事实（如 `MaterialInfoFact`，按 key 唯一）与列表事实（如 `SalesOrderListFact`，字段多为 cardinality many）；
- 载体：`ontology/fact-types.yaml`。

### ③ 能力行动层（Capability / Action）

回答"Agent 能做什么、如何被选中"。

- 能力以 `capabilityId` 构成**注册闭集**，LLM 只能从闭集中选择，不得生成任意能力名或 RFC 名；
- 两类能力互斥：
  - **Function**：只读、无副作用、无需审批；
  - **Action**：写入类，执行前必须存在 recorded human confirmation；
- 每个能力声明：意图（关键词/澄清策略）、类型化 inputs、Fact outputs、governance、narrative（叙述形状）、executorBinding；
- 载体：`registry/capabilities.yaml`。

### ④ 事理治理层（Rules / Governance）

回答"什么是业务上允许的、什么必须被拦截"。

- **结构不变量**：Function 必须只读、Action 必须人审、闭集校验、参数约束——由 validator 确定性强制执行，是唯一真相源；
- **审批与数据治理**：`governance.approvalPolicy / sideEffect / dataClassification / auditRequired`；
- **业务规则**（补货逻辑、风险阈值等）：当前部分在确定性代码中；未来需要沉淀时建立声明式规则目录，带来源、版本、适用范围，不散落进 prompt；
- 载体：`scripts/validate-registry-contract.py`、`scripts/validate-semantic-planning-contract.py`、capability `governance`。

## 3. 层间链接

| 链接 | 连接 | 形式 |
|---|---|---|
| **类型桥** | 能力参数 → 术语层 | input/output 的 `semanticType`（OWL 镜像：`rdfs:range`） |
| **事实边** | 能力入参 → 上游 Fact | `satisfiableByFactType`；确定性派生 producer→consumer 依赖边（见 `derive-data-dependencies.py`），不手工回写 |
| **Grounding** | 语义参数 → 技术参数 | 绑定目录中的 `inputMapping` / `filterMapping`，单向且只允许绑定目录持有 |
| **反馈边** | 执行结果 → 事实层 | Action receipt Fact（如 `PurchaseRequisitionCreatedFact`） |

运行时链路：意图召回 → 按语义类型抽槽 → 缺槽澄清 → 上游事实补槽 → 组装 CallPlan（仅 capabilityId + 类型化参数）→ Gateway 经绑定映射到 BAPI/OData。

## 4. 不可逾越的硬边界

1. LLM 只从注册能力闭集选择；Gateway 只接受 `capabilityId`，不接受请求提供的 `rfcName`；
2. READ 能力不得调用 `BAPI_TRANSACTION_COMMIT/ROLLBACK`；
3. WRITE 能力在人工确认记录存在前不得执行——任何模型置信度都不能豁免；
4. 缺失或非法参数必须在到达 SAP 前拦截（validate-before-execute）；
5. 技术映射（bindingId/RFC/URL/凭据）只存在于 allowlisted 绑定，请求与 LLM 不可携带；
6. 控制流、权限、副作用留在确定性代码，模型只填判断；业务规则不进 prompt。

## 5. 落地状态

| 项 | 状态 |
|---|---|
| Fact predicate 落为带 domain/range 的 OWL 属性，单值事实函数式 | 已完成（2026-09） |
| 标量值类型建模为派生数据类型；`Function disjointWith Action` | 已完成（2026-09） |
| 依赖边确定性派生（`Material.GetInfo → PR.CreateDraft`） | 已存在并接线 |
| IOPE 前置条件 / 审批策略 ODRL 化 | 待办 |
| 业务规则声明目录 | 待办（按需） |
| fact JSON → Turtle 序列化器（`scripts/serialize-facts-turtle.py`，单向） | 已完成（2026-09） |
