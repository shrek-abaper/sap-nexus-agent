# Outcome

用户在 DSH Chat 中用不完整的业务描述（不知道编码）查询物料、客户、供应商相关业务时，系统从受治理的 PostgreSQL 主数据检索投影中搜索真实候选，必要时向用户消歧提问，获得明确选择后把真实编码绑定到原业务能力的参数并恢复执行。真实编码只能来自受治理的数据访问，模型无权编造。

# Scope

按提示词 `docs/prompt/claude-code-ontology-entity-resolution-implementation.md` 的阶段 A–D：

1. 阶段 A：实体解析逻辑契约（EntityMention / Entity / EntityCandidate / ResolvedEntityRef 分离建模）、`ontology/entity-resolution.yaml` 及 schema/validator、PG schema 与迁移、合成快照导入器（full snapshot、staging + 原子发布、幂等）、真实 PG Provider、经 Gateway 治理链的受控 READ 搜索接入。
2. 阶段 B：Material 端到端——待解析 mention、服务端候选集、ENTITY_CHOICE 一等 pending 状态、DSH Chat 候选卡片、按钮与受约束自然语言选择、可信编码绑定并恢复 `MM.Inventory.GetAvailability` 执行（FakeGateway 验证恢复链路，明确标注合成/模拟）。
3. 阶段 C：Customer、Supplier 复用同一解析机制与状态机；Customer 按声明绑定到 `customer`（FI.AR.GetOpenItems）与 `customerNumber`（SD.SalesOrder.GetList）等不同槽位名；Supplier 绑定到 `vendor`（MM.PurchaseOrder.GetList、FI.AP.GetOpenItems）；object-types.yaml 补齐 Customer 对象类型。
4. 阶段 D：提示词 §11 的回归用例（检索/数据 12 条、选择/会话 11 条、集成/安全 7 条，可组合实现）、反向安全用例、运行文档与回滚说明、§13 交付清单。

# Non-goals

- SAP 侧自开发、真实 SAP 主数据提取器、生产同步/CDC。
- HANA Adapter 真实实现（保持明确"未实现"，不存在返回成功的伪 Adapter）。
- 全企业主数据治理平台、自由 SQL、通用动态数据接入、embedding/向量检索、Open Ontologies/图数据库依赖。
- 基于一次用户确认永久学习公共别名；新增 SAP 写入场景；改变既有 WRITE 审批要求。
- 重写 Harness、Planner、Gateway 架构；把现有业务逻辑改成本体规则。
- 生产身份授权改造（当前 placeholder principal 明示 sandbox 限制）。

# Acceptance examples

1. 用户输入"查一下蓝色耐高温密封圈在 1000 工厂的库存"→ 系统不编造物料编码，发起 Material 搜索并展示含正式描述、编码、区分属性的候选卡片；用户选"第二个"→ 绑定原候选集第二项的真实编码与保留的 plant=1000，恢复库存查询（FakeGateway），结果标注合成/模拟。
2. 描述模糊命中即使只有一个候选 → 系统请求用户确认，不自动绑定；用户确认前的任何时刻不触发下游库存/账款业务读取。
3. 用户输入精确且当前可见有效的编码 → 经 get-by-key 验证存在性与状态后直接绑定，保留验证证据。
4. 同名不同规格物料（如前导零、小数规格、不同语言描述）→ 产生多个去重后的候选，同一实体的多语言/别名/组织 join 行不重复计数。
5. 客户简称对应多个法人 → 候选卡片展示区分属性；用户按城市选择仍歧义时继续追问；确认后按目标能力分别绑定 `customer` 或 `customerNumber`。
6. 用户回答"都不是"/补充新描述/切换业务目标 → 旧候选句柄失效，不能继续选中，旧 confirmed slot 不吞掉新描述。
7. 过期候选、旧 state version、跨会话/跨用户句柄、伪造 candidate-set ID → 服务端拒绝，不获得执行权威。
8. SQL 注入与 LIKE 通配符输入 → 不改变查询结构、不扩大权限；数据库不可用/超时明确分型，不冒充"无候选"。
9. full snapshot 重复导入幂等；格式错误批次不部分发布；只替换声明覆盖范围；失效对象不再作为有效候选。
10. 实体选择确认不产生 WRITE ApprovalRecord；既有写审批 subject 含最终规范编码，对象改变则旧审批失效。
11. 无 PG 配置或 feature flag 关闭 → 旧编码路径行为按声明保持，不悄悄猜码降级；描述字段中的恶意指令按普通数据展示，不改变工具调用与权限。
12. 配置/语义版本或 PG 快照变化 → 旧未完成选择安全失效并要求重新确认，不静默替换用户选择。

# Constraints and invariants

- PG 是 SAP 主数据只读检索投影，不是第二权威源；SAP 属性不允许通过解析 API 改写。
- 本体声明逻辑对象/身份/属性/解析策略/语义绑定；不含数据库凭据，不暴露物理表或自由 SQL；物理映射为服务端可信配置，用户与 LLM 不可改表名列名。
- 搜索作为注册 READ 能力经现有 Gateway 安全边界访问；DSH/浏览器/Python 子进程不直接获得 PG 凭据；不提供任意 SQL/表名/库地址入口。
- 可信 principal/系统/client/组织范围由服务端注入，在查询/分页/排序/计数之前落实；客户端组织参数只能收窄。
- READ 能力不得调用 BAPI_TRANSACTION_COMMIT/ROLLBACK；WRITE 审批链路不变。
- `reduce_context()` 保持无 IO 纯 reducer；搜索与 get-by-key 在 IO 编排层执行，产出已验证事件后交 reducer；实体候选列表不冒充 capability 候选列表（不滥用 CAPABILITY_CHOICE）。
- 模型不得生成规范编码直接执行、不得指定数据库/SQL/bindingId/可信范围、不得把"我选了第二个"自证为有效编码；服务端校验对象类型与目标输入 semanticType 一致。
- 编码使用字符串，保留前导零/字母数字/小数规格/特殊字符；不做通用补零或整数转换。
- 凭据、连接串不进入聊天、命令参数、代码、日志或提交；使用仓库批准的凭据注入方式。
- SemanticRelease 使用显式源清单：新增语义文件必须显式登记并过一致性校验；数据版本与语义版本分离。
- 合成 fixtures 严禁使用真实客户数据；离线基线不依赖付费模型。
- 仓库事实基线：HEAD=b622857；object-types.yaml 现有 Material/Plant/Supplier/PurchaseOrder/PurchaseOrderItem，无 Customer（本次补齐）；executor 枚举为 JCO_RFC/ODATA/CDS_ADT/CDS_ODATA/REST_JSON，无 SQL 类型。

# Decisions

- D1（用户确认，2026-10-20；当日完成）：PG 环境由用户用 sudo 安装 `postgresql` + `postgresql-contrib`；已验证 PG 16.15 运行中、peer 认证免密可用、测试库 `sap_nexus_dev` 已建、pg_trgm 1.6 可用。连接统一走 UNIX socket + peer 认证，凭据不进聊天/代码/日志。
- D2（2026-10-20 探证完成）：Gateway 接入采用**新增 executor 类型 `PG_MASTERDATA_READ` + Gateway 窄 TechnicalAdapter（Java，连接池 + pgjdbc，固定参数化查询、白名单映射）**。探证结论：现有 REST_JSON Adapter 硬编码 rest2rfc/SAP 语义（URI 强制 `?RFC=`、Basic Auth 用 SAP 凭据变量、ErrorType 全为 SAP_*、审计元数据写 rfcName），用于本地 PG 搜索会污染错误分型与审计，不满足提示词 §3.1 的错误分型要求；改造其通用化又会影响已 live 验证的 SAP 路径，放弃。Java 侧消费点有限（schema enum、BindingDefinition、dispatcher 按 bean 名路由无需改、validate_registry_contract.py、registry 测试），改动可控。
- D3（用户确认，2026-10-20）：本特性走 Comet Native 单一 change（entity-resolution-master-data），按阶段 A–D 分批 Build。
- D4（工程默认，提示词 §6.3 允许）：第一版采用保守确认策略——仅"精确编码 + 当前可见 + 有效"可直接绑定（附验证证据）；精确名称/别名唯一命中也请求用户确认；模糊命中一律确认。
- D5（工程默认）：自然语言选择第一版用确定性解析（序数"第二个"、"都不是"、按候选真实属性过滤）；模型建议仅作候选引用且服务端仍验证集合成员与唯一性；离线基线不依赖付费模型。
- D6（工程默认）：查询超时、候选数量上限、澄清轮次上限为可配置工程保护值，默认值声明为未经过生产校准；生产 p95/并发/费用预算记为"待确认"。
- D7（仓库事实）：Customer 对象类型缺失需补齐并对齐 `sapnexus:CustomerNumber`；同一 Customer 引用须映射 `customer`（FI.AR）与 `customerNumber`（SD.SO）槽位名；Supplier 映射 `vendor`。

# Open questions

（无未决问题；共享理解已于 2026-10-20 经用户显式确认）

# Verification expectations

- 阶段 A 退出：合成数据在真实 PG 上完成三类对象搜索与 get-by-key；权限/范围过滤、错误分型、去重、截断/覆盖信息测试通过；不用 Mock Provider 替代全部 PG 集成测试。
- 阶段 B 退出：DSH Chat 同一会话从描述到选择到恢复库存能力；未确认前不执行业务读取；无 UI 自动化能力时交付协议级自动化测试 + 可复现手工步骤并明示 UI 未实测。
- 阶段 C 退出：三种对象共用同一解析服务与状态机；槽位映射正确；原目标与其他参数保留。
- 阶段 D 退出：提示词 §11 回归用例机器可跑；SQL 注入/越权/过期重放/版本漂移/恢复执行有反向测试；基线失败与新增失败分别记录；禁止删测试、降断言、乱更基线。
- 验证分层诚实标注：单元 / 真实 PG / FakeGateway / 前端协议或 UI / SAP live（未授权则明确未做）。
