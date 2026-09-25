# Identity Foundation

## Purpose

为业务对象提供与系统编码无关的稳定身份，回答"谁是谁"，并以别名登记与冲突检测为未来
跨系统实体合并预留接口。

## Requirements

### Requirement: 确定性 canonical identity

系统 SHALL 由业务对象类型与一组 keyedBy 标识符内容寻址地派生 canonical identity；
同输入 MUST 恒等且可复现，不依赖具体系统编码。

### Requirement: 解析、别名与冲突检测

系统 SHALL 支持 resolve（返回 identity 与 direct/alias/new 判定）与 register_alias。
当同一标识符集合映射到不同 canonical identity 时 MUST 报冲突，不得静默归并。
未知 object 类型或空标识符 MUST 被拒绝。

### Requirement: 纯解析不产生副作用

身份解析 MUST NOT 执行网络/SAP 访问或修改其他状态，且不参与授权决定。

## Non-goals

- 跨系统自动/概率实体匹配与合并（待第二数据源）；
- 替换 MatchDecision、Gateway、审批、WRITE 链、补货、Impact Analysis。
