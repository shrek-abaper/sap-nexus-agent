# List BAPI Executor Migration

## Purpose

将主事实 live 等价已证实的三个 list 类能力（FI.AP、FI.AR、SD.SalesOrder）的
生产执行路径从 JCO_RFC 切换到 REST_JSON，使其经纯 ABAP SICF rest2rfc 网关返回
数据，同时保持能力的输入/输出契约、字段映射与错误 fail-closed 行为不变。

## Requirements

### Requirement: 三能力 executor 切换到 REST_JSON

`FI.AP.GetOpenItems`、`FI.AR.GetOpenItems`、`SD.SalesOrder.GetList` SHALL 以
`type: REST_JSON` 的 executor 与对应 REST binding 执行；executor 块 MUST 保留
各自原有 `rfcName`、`inputMapping`、`outputMapping` 内容，MUST NOT 在迁移中
改变映射语义。catalog SHALL 为三个能力各提供一条 REST_JSON binding，连接值与
凭据 MUST 继续经 Gateway 受控配置解析，registry MUST NOT 出现连接字面值。

### Requirement: 迁移后主事实 live 等价

迁移后三个能力经 SICF 返回的主事实 SHALL 与 JCo 基准等价：AP 28,197 行 /
131 字段、AR 1,355 行 / 124 字段、SD 5,164 行 / 54 字段（对应输入分别为
vendor 0000003120/company 2100；customer C00403/company 2100；customer
C00002/sales org 2110/document date 20260112）。live harness MUST 在迁移后
重新运行并以实际输出作证据，不得只引用迁移前记录。

### Requirement: 快照与回归一致

binding catalog 与 capabilities 的变更 SHALL 产生新的 registry snapshot hash，
evals 中的 snapshot pin MUST 同变更更新；registry contract、Gateway Java tests、
agent 全量测试与全部 evals MUST 通过。旧 JCO_RFC bindings SHALL 保留在 catalog
中。

### Requirement: 边界不放松

三个能力 SHALL 保持只读；凭据三路共享模型、错误 fail-closed 分类与（WRITE
能力的）人工审批边界 MUST NOT 因迁移改变。SD 已知的"业务错误时 SICF 无 RETURN
文本"取舍 MUST 保持非 200 状态码分类，不得将其静默判成功。

## Non-goals

- 迁移 MM.Inventory、MM.Material、WRITE 能力；
- 改动 Java runtime / 前端、删除旧 binding、改变任何映射语义。
