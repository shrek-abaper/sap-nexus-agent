# Ontology Constraint Runtime

## Purpose

在运行时以标准 SHACL / 本体图回答"输入值是否满足约束、前置条件是否成立"，替代对 registry
YAML 的手写 Python 解释；控制流与强制不变。registry YAML 仍是唯一人工作者源，标准产物由
构建时代码生成并与快照哈希绑定。

## Requirements

### Requirement: 约束产物由 registry YAML 构建生成

系统 SHALL 提供一个确定性 codegen，读取 `registry/capabilities.yaml`（唯一作者源），生成：

- 每个能力一个 SKOS Concept，prefLabel 为名称，altLabel 为别名与纯文本强触发关键词；
- 每个有约束的入参一个 SHACL NodeShape，包含 datatype / minLength / maxLength / pattern；
- manifest：各产物 sha256，并绑定 registrySnapshotId。

同输入两次生成的产物与哈希 MUST 完全一致；regex 形关键词不得作为 SKOS 标签。
生成产物不可手工编辑；系统 SHALL 校验产物与当前 YAML 同步，不同步即失败。

### Requirement: 参数校验由 SHACL 标准引擎求值

运行时参数合法性 SHALL 由 pyshacl 对生成的 SHACL NodeShape 求值得到，不再由
`_valid_semantic_input_value` 逐种约束的定制 Python 解释。批量 preflight 与 READ authority
两处调用点 MUST 使用同一解析结果。

数值类型 MUST 保留为 xsd:decimal（不得退化为字符串导致 datatype 判定失败）。

### Requirement: 前置条件解析器对版本化图求值

系统 SHALL 提供对版本化图的前置条件解析器，覆盖 required / requiredWhen（含条件前置
K→cost_center）与 requireAny 分组，缺失项结果与执行边界口径一致（可由上游 Fact 满足的
入参不算缺失）。查询计划 MUST 预编译并按快照缓存，不得逐请求重新解析。

该解析器在本阶段作为受测试的能力交付（执行边界的 SHACL 校验已接入生产）。生产中
"缺槽 → CLARIFY" 仍由 capability_selector 投影同一 registry 决定；将 selector 完全切换到
图查询是紧邻的下一增量，不在本次范围。

### Requirement: resolve 与 enforce 分离

图/SHACL 引擎只产出"满足/不满足"的解析结果；拦截、控制流、副作用、权限决定 MUST 仍由
确定性代码执行。图结论不可直接放行 WRITE，也不可豁免 recorded human confirmation。

### Requirement: 语义层不持有系统凭据

约束运行时 MUST NOT 持有 SAP 凭据或直连 SAP；其输入为 registry、生成产物与会话槽位，
不产生网络副作用。

## Non-goals

- 能力 SKOS 召回接入、WRITE ODRL 权限运行时绑定（后续 Phase）；
- Event/State 迁移链、Change Propagation、跨系统 Identity（候选，另行立项）；
- 替换 MatchDecision 五态、Gateway、审批 store、确定性补货算法。
