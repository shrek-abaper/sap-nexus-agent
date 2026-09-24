# Go / No-Go 决策报告：运行时本体绑定

- **日期**: 2026-09-24
- **依据**: Task 1–5 全部证据（本目录与 spike README）
- **决策**: **有条件 Go**——进入 Phase 1，但采用**轻量自建 rdflib binding**，不引入全量 Semantica 平台；立项按 Comet HEAVY 流程

---

## 1. 决策摘要

```text
问题：是否采用 Semantica 作为本体运行时？
回答：不作为平台引入；采用其验证过的架构，以 rdflib 自建等价 binding。
      Semantica 保留为未来需要更重能力（PROV-O/决策记录/图分析）时的候选。
```

## 2. 证据汇总（Task 1–5）

| Task | 结论 |
|---|---|
| 1 现有 OWL 加载 | 发现并修复 11 处 `parseType` 非法值；图可被 RDF 运行时原样接受 |
| 2 bundle codegen | SKOS（85 triples）+ SHACL（29 shapes/227 triples）；哈希可复现；与作者本体零重叠拼接（648） |
| 3 四类查询 | 9 项正反控制全 PASS；修复作者 OWL 的 CURIE 系统性缺陷（10 文件） |
| 4 eval 回放 | 28 用例五维度全部 100% 一致（选择 28/28、缺槽 26/26、校验 26/26、权限 7/7、expected 26/26） |
| 5 资源/稳定性 | 加载 19.3ms、RSS 峰值 59MB、召回 2.5ms；回放逐字节稳定、延迟漂移 <3% |

## 3. 为什么是"自建轻量 binding"而非"采用 Semantica"

Spike 实际只使用了 Semantica 能力的一个小子集，且均可由标准轻量组件替代：

| Spike 实际用到 | 轻量替代 |
|---|---|
| 图加载 / SPARQL | **rdflib**（纯 Python，单一依赖） |
| SHACL 校验 | **pyshacl**（独立库，Semantica 本身不含 SHACL 引擎） |
| 可执行条件求值 | **本项目自建**（OWL-S/ODRL 文件只携带标签/定义） |

而 Semantica 的代价不对等：

- 重依赖（numpy/pandas/scipy/pyarrow/grpc…），仅适合旁路；
- 其增值能力（PROV-O、决策一等对象、Rete/Datalog、图分析）**当前无消费场景**；
- 引入平台会让架构被其全家桶绑定，与"嵌入而非侵入、最小必要"原则冲突。

结论：**真正的资产是 Task 2 的 codegen 与查询契约，不是 Semantica 平台本身。**

## 4. Go 的前置条件（全部满足才进入实现）

1. **Comet 立项**：Phase 1 跨模块、改消费方，属 HEAVY，不在 spike 目录直接改；
2. **codegen 出 spike**：把 `build_bundle.py` 提升为项目正式构建步骤（YAML 为唯一作者源，产物绑定 registrySnapshotId 哈希）；
3. **查询延迟治理**：preconditions/permission 的 SPARQL 做**计划缓存/预编译**（Task 5 测得约 40ms，不可逐请求解析）；
4. **边界保持**：resolve（图）与 enforce（确定性代码）分离；不给语义层 SAP 凭据；WRITE 凭证仍只认 ApprovalRecord。

## 5. Phase 1 范围（建议）

- 仅切**参数校验（SHACL）与前置条件求值**到本体解析；强制仍由现有代码执行；
- SKOS 召回与 WRITE 权限绑定分别在后续 Phase（先 shadow 只记录，再切换）；
- 实例事实入图 / 跨域推理不在范围（须另行立项）。

## 6. 风险登记

| 风险 | 缓解 |
|---|---|
| YAML 与生成产物漂移 | 构建时代码生成 + 快照哈希，产物不可手改 |
| 条件求值被误当图能力 | 明确自建、随消费方代码测试 |
| rdflib 查询性能 | 查询计划缓存；按快照缓存图 |
| 范围蔓延 | Phase 边界固定；实例图另立项 |

## 7. 结论

- **对"运行时本体绑定"方向：Go**——静态语义等价已被 28 用例证明，成本低、可复现；
- **对"采用 Semantica 平台"：No-Go（当前阶段）**——以 rdflib + pyshacl 自建等价轻量层；
- Semantica / EvoOntology 保留在提案 §10，作为未来能力升级时的复用评估对象。
