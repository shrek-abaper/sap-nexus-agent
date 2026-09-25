# REST JSON Registry Contract

## Purpose

定义 REST_JSON 在 registry schema、契约校验、垂直切片等价验证与迁移评估方面的
契约，使新执行器的引入可被静态校验、其与 JCO_RFC 的行为等价可被 live 证据证明、
后续逐个 RFC 迁移有明确归属，且全过程不放松凭据与审批边界。

## Requirements

### Requirement: 能力 schema 支持 REST_JSON

能力 schema 的 `executor.type` 枚举 SHALL 包含 `REST_JSON`；REST_JSON 能力的
executor 块 SHALL 与 JCO_RFC 同构地要求 `rfcName`、`inputMapping`、
`outputMapping`。binding catalog schema 已有的 REST_JSON 条件必填
（`systemRef`、`method`、`pathTemplate`、`request`、`response`、`auth`）MUST 保持，
`executorBinding.type` 与能力 `executor.type` 一致的既有交叉校验 MUST 保持。

### Requirement: 契约校验匹配真实 POST 网关

契约校验器 SHALL 将 dynamic 模式 REST_JSON Function binding 的 `method` 校验为
POST（取代早期假设 GET 的规则），并保留：Function binding 必须 read-only、MUST NOT
含原始 url/headers/payload、auth 中 MUST NOT 出现 token/apiKey/secret/password/
connectionString 等明文凭据键。缺任一 REST 必填字段或含禁用键时 MUST 报错；合规
binding 与现有全部 registry 内容 MUST 校验通过。catalog 中允许存在暂未被能力引用的
REST binding（为 live 验证后的翻转做预置）。

### Requirement: 垂直切片等价验证资产

系统 SHALL 提供以 `FI.AP.GetOpenItems`（BAPI_AP_ACC_GETOPENITEMS）为对象的 live
等价验证：默认跳过、仅当显式 live 开关启用时运行；验证 SHALL 使用同一组输入分别
经过 SICF rest2rfc 与现有 JCO_RFC 路径，逐行比对 openItems（凭证号、公司代码、金额、
货币、到期基准日、供应商等关键字段）与 return。凭据 SHALL 仅从环境变量读取；
未运行时验证结果 MUST 以"跳过 + 原因"记录，不得计为通过。

### Requirement: 迁移评估清单

系统 SHALL 产出逐个现有 RFC 的迁移评估清单，依据输出形态（EXPORTING 标量/结构、
TABLES、深层嵌套、RAW 字段、动态反射已知取舍）标注三类归属：可迁 REST_JSON（动态
模式无损）、保留 JCO_RFC（动态模式有损）、走 typed 契约；每个结论 MUST 可追溯到
实测或函数形态证据，不得给"假设无损"的结论。

### Requirement: 回归全绿

新增契约与执行器代码 MUST 满足：agent 全量测试、Gateway 全量 Java 测试、registry
契约校验与全部 evals 通过；live 验证默认跳过 MUST NOT 破坏 CI。binding catalog 的
新增条目会改变 registry snapshot：eval 中的 snapshot pin MUST 在同一变更内以重新
生成的 hash 同步更新，不得在 hash 失配时宣称通过。

### Requirement: 三路共享 SAP 受控配置

JCO_RFC、ODATA、REST_JSON SHALL 共用同一套 SAP host、client、user、password
受控配置；JCo 路径以实例号寻址（非 HTTP），OData 与 SICF rest2rfc SHALL 共用同一
ICM HTTP 端口、仅以 URL 路径区分。REST_JSON endpoint MUST 缺省由共享 host 与 HTTP
端口派生，`SAP_REST2RFC_*` 仅作为可选覆盖；任何路径都 MUST NOT 在 registry 中出现
连接字面值或凭据。

## Non-goals

- 在本变更内执行实际生产翻转或 WRITE 迁移；
- 放宽凭据、审批、只读任一边界；
- typed 契约的实现与批量迁移。
