# Phase 1 立项输入：运行时本体绑定（约束层标准化）

- **用途**: 通过 `/comet` 立项时直接引用本文件
- **配套**: 完整方案见 `runtime-ontology-binding.md`（§5 阶段、§13 前后对比）；
  证据见 `spikes/semantica-shadow/`
- **信号**: HEAVY（跨模块、>5 文件），预期路由 Native

## 背景

- shadow spike 已完成：28 个 eval 用例五维度 100% 语义等价；
  Go/No-Go 决策为"有条件 Go"
- 采用 **rdflib + pyshacl 轻量自建**，不引入全量 Semantica 平台

## 本次范围（Phase 1）

1. 将 spike 的 `build_bundle.py` 提升为正式构建步骤：
   registry YAML（唯一作者源）→ SKOS + SHACL canonical bundle，哈希绑定 registrySnapshotId
2. 参数校验改由 pyshacl 对 SHACL NodeShape 求值（替换 `_valid_semantic_input_value` 的定制解释）
3. 前置条件（required / requiredWhen）改为版本化图查询，**必须做查询计划缓存**（spike 测得约 40ms）
4. resolve/enforce 分离：图只解析，拦截/控制流/副作用仍由确定性代码执行

## 明确不变

- MatchDecision 五态、Gateway、WRITE 人工审批（ApprovalRecord 唯一凭证）、确定性补货逻辑全部不动
- SKOS 召回、WRITE ODRL 权限绑定属后续 Phase，不在本次
- 不给语义层 SAP 凭据

## 成功判据

- 全量 agent 测试与 evals 全绿；行为与改造前一致（28 用例口径）
- codegen 同输入哈希可复现；校验查询经缓存后延迟可接受

## 后续候选（不在本次）

- Event/State 状态迁移链
- Change Propagation（规则/语义变化的影响分析）
- Identity 跨系统对齐（待跨系统场景触发）
