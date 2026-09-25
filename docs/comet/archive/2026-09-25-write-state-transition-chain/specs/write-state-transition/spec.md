# Write State Transition Chain

## Purpose

把 WRITE（审批驱动的 SAP 写入）的状态迁移因果链作为 ApprovalRecord 的一等持久化字段，
支持按审批记录回放"对象在何时、因什么事件、依据什么证据、从哪个状态迁到哪个状态"。
迁移链只作审计证据，不参与授权。

## Requirements

### Requirement: 迁移记录建模为不可变值对象

系统 SHALL 为每次状态迁移保存一条不可变记录，包含：`from_state`、`to_state`、`event`、
`timestamp`、`actor` 与 `evidence_ref`。evidence_ref MUST 指向触发该迁移的证据
（gateway trace、SAP 执行回执等）的引用，不得复制敏感载荷或参数明文。

### Requirement: ApprovalRecord 持久化 append-only 迁移链

ApprovalRecord SHALL 携带 `transitions` 有序集合，只可追加：

- 创建记录时 MUST 记录初始 `None → pending`；
- approve / reject / mark_executed 的每次合法切换 MUST 经同一通道追加对应迁移；
- 迁移链 MUST 随 `to_dict` 序列化、`from_dict` 反序列化；
  不含 transitions 的旧记录 MUST 兼容为空链。

### Requirement: 迁移链可随记录按 approval_id 回放

系统 SHALL 能仅依据 ApprovalRecord（不依赖外部 trace 文件）读取整条迁移链，
顺序与真实切换一致。迁移链 MUST NOT 依赖可被环境变量重定向的进程内文件。

### Requirement: 迁移链不参与授权

transitions 是审计/证据产物；拦截、授权、控制流、副作用 MUST 仍由确定性代码与现有审批门禁
执行。迁移记录 MUST NOT 直接放行 WRITE 或豁免 recorded human confirmation。

## Non-goals

- READ 侧状态机、Change Propagation、跨写入编排与补偿事务；
- 改变 ApprovalState 四态与合法性、Gateway、审批 store、确定性补货。
