# Ontology Constraint Runtime

## Purpose

在运行时以标准 SHACL / 本体图回答"输入值是否满足约束、前置条件是否成立、缺失入参应由用户
补充还是规划器推导"，替代对 registry YAML 的手写 Python 解释；控制流与强制不变。
registry YAML 仍是唯一人工作者源，标准产物由构建时代码生成并与快照哈希绑定。

## Requirements

### Requirement: 约束产物由 registry YAML 构建生成

系统 SHALL 提供一个确定性 codegen，读取 `registry/capabilities.yaml`（唯一作者源），生成：

- 每个能力一个 SKOS Concept，prefLabel 为名称，altLabel 为别名与纯文本强触发关键词；
- 每个有约束的入参一个 SHACL NodeShape，包含 datatype / minLength / maxLength / pattern；
- manifest：各产物 sha256，并绑定 registrySnapshotId。

同输入两次生成的产物与哈希 MUST 完全一致；regex 形关键词不得作为 SKOS 标签。
生成产物不可手工编辑；系统 SHALL 校验产物与当前 YAML 同步，不同步即失败。

### Requirement: 参数校验由 SHACL 标准引擎求值

运行时参数合法性 SHALL 由 pyshacl 对生成的 SHACL NodeShape 求值得到。批量 preflight 与
READ authority 两处调用点 MUST 使用同一解析结果。数值类型 MUST 保留为 xsd:decimal
（不得退化为字符串导致 datatype 判定失败）。

### Requirement: 前置条件解析器对版本化图求值

系统 SHALL 提供对版本化图的前置条件解析器，覆盖 required / requiredWhen（含条件前置
K→cost_center）与 requireAny 分组，缺失项结果与执行边界口径一致（可由上游 Fact 满足的
入参不算缺失）。查询计划 MUST 预编译并按快照缓存，不得逐请求重新解析。

### Requirement: 意图路由缺失分区由 runtime 单一解析

系统 SHALL 在 runtime 提供意图路由视角的缺失解析：对给定能力与已提供键，分别产出

- `missing_user`：必需、未提供且在**本次 governed sources** 内不存在可自动拉取生产者的入参；
- `missing_derivable`：必需、未提供但可由 governed sources 内自动拉取生产者推导的入参。

可推导性 MUST 复用派生数据依赖（消费者 satisfiableByFactType 与生产者 semanticType 匹配）
并要求生产者在 governed sources 内为 active 的 READ/auto-pullable 能力；不可读全量 registry。
解析为声明查询（无 Gateway/RFC/SAP 调用）；解析失败 MUST fail closed（归入 missing_user）。

消费方（capability_selector）MUST 以该分区作为唯一权威做路由：missing_user 非空 → CLARIFY；
missing_user 空且 missing_derivable 非空 → ESCALATE_TO_PLANNER；两者皆空 → SELECT。
selector MUST NOT 保留与之重复的 required/derivable 调和实现。

### Requirement: resolve 与 enforce 分离

图/SHACL 引擎只产出"满足/不满足"的解析结果；拦截、控制流、副作用、权限决定 MUST 仍由
确定性代码执行。图结论不可直接放行 WRITE，也不可豁免 recorded human confirmation。

### Requirement: 语义层不持有系统凭据

约束运行时 MUST NOT 持有 SAP 凭据或直连 SAP；其输入为 registry、生成产物与会话槽位，
不产生网络副作用。

## Non-goals

- Event/State 迁移链、Change Propagation、跨系统 Identity（后续/待触发）；
- 替换 MatchDecision 五态、Gateway、审批 store、确定性补货算法。
