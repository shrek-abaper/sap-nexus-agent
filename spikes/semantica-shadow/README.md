# Semantica Shadow Spike

旁路 shadow spike（见 `docs/proposals/runtime-ontology-binding.md` §12）：在隔离环境中评估
Semantica 作为本体运行时；不接 SAP、不给凭据、不改生产执行链路。

## 环境

```bash
python3 -m venv .venv
.venv/bin/pip install semantica pyoxigraph
.venv/bin/semantica doctor          # Neo4j/faiss/embeddings 可选，本 spike 走嵌入式 RDF
```

- Semantica 0.7.0 / pyoxigraph 0.5.11 / Python 3.12
- 图存储：`graph/`（gitignore），嵌入式 Oxigraph

## Task 1：现有 OWL 加载验证 — 已完成（2026-09-24）

### 发现的真实缺陷

`ontology/*.owl` 中 11 处 `owl:withRestrictions` 误用了非法的
`rdf:parseType="Constraint"`，正确值是 **`rdf:parseType="Collection"`**。
非法值导致每个限制块静默丢失一条连边（11 条三元组），但文件 XML 仍良构、
registry 子串门禁也无法发现——只有真正做 RDF 解析才能暴露。已全部修正。

### 加载方式

Semantica 的 Triplet 加载器不支持 blank-node 主体，而数据类型限制必然包含
blank `rdf:Description`，因此：

- 通过底层 pyoxigraph `Store.bulk_load(bytes, format=RdfFormat.RDF_XML)` 原生加载（bnode 保留）；
- 在同一图上经 Semantica `OxigraphStore.execute_sparql` 查询。

脚本：`scripts/load_graph.py`

### 计数核对（修正后）

| 口径 | 三元组 |
|---|---|
| 11 文件分文件合计（rdflib） | 343 |
| 跨文件重复 | -7 |
| **合并图（rdflib union）** | **336** |
| **Oxigraph SPARQL count** | **336** |

两口径完全一致。

### 项目门禁（修正后）

- registry contract valid；
- test_contract_files + test_derived_dependencies：86 passed。

## Task 2：bundle codegen — 已完成（2026-09-24）

脚本：`scripts/build_bundle.py`（输入：`registry/capabilities.yaml`；产物：`bundle/`）

| 产物 | 内容 | 规模 |
|---|---|---|
| `skos-capabilities.ttl` | 挂到已有 `ontologyIri` 个体：prefLabel(name)、altLabel(aliases)、definition、example、inScheme | 68 triples |
| `shacl-inputs.ttl` | 每个有约束的入参一个 NodeShape：datatype / minLength / maxLength / pattern | 29 shapes，227 triples |
| `manifest.json` | 两文件 sha256 | — |

验证：

- **连续两次构建哈希一致（可复现）**；生成过程修复了 Turtle 语句分隔符缺陷；
- 两个文件均无 blank node；rdflib 解析通过；
- SHACL 与 YAML **逐条交叉核对 82 条约束**（含 datatype），全部一致；
- 与作者 OWL 合并加载：336 + 68 + 227 = **631 triples，零重叠**。

## Task 3：四类查询适配 — 已完成（2026-09-24）

脚本：`scripts/query_shadow.py`；正反控制：`scripts/assert_controls.py`（9 项控制全部 PASS）

| 查询 | 数据通道 | 正/负控制 |
|---|---|---|
| 参数校验 | 图上 SHACL NodeShape，经 **pyshacl** 求值 | plant=1000 通过 / plant=12 被 pattern 拒绝 |
| 前置条件 | SHACL required 标记 + extraction.requiredWhen 条件 | 键齐全满足 / 缺两键报告 / **K→cost_center 条件前置** |
| 权限 duty | ODRL 图解析 duty，审批记录按 duty 定义求值 | 审批+哈希匹配放行 / 哈希不符拒绝 |
| SKOS 召回 | 图上 pref/alt 标签匹配 | "查库存"命中 / 无关文本为空 |
| 跨后端 | 同一 SPARQL 在 Semantica Oxigraph 后端运行 | 7 concepts |

### 本任务暴露的系统性缺陷（均已修复）

1. **CURIE 写入 RDF/XML 属性值**：`rdf:about/rdf:resource` 的值是 URI 引用，不做命名空间展开；
   此前全部 10 个作者 OWL 文件的节点都是相对 IRI `sapnexus:X`。已统一替换为完整 IRI；
2. **validator 兼容两种形式**：`_ontology_contains` 同时接受 CURIE（旧夹具）与 `#LocalName`（作者文件）；
3. 同步更新了一项既有测试断言的形式（`test_inventory_ontology_identity_exists` 改为断言完整 IRI，
   测试意图"本体中存在该能力标识"不变）。

### 关键架构结论

**采用 Semantica 不会让 OWL-S/ODRL 自动可执行**：作者文件中的前置条件/duty 只携带标签与定义，
可计算条件仍须由确定性代码对 registry / 审批记录求值。这直接计入 Go/No-Go 评估。

## Task 4：eval 回放双路径对比 — 已完成（2026-09-24）

脚本：`scripts/replay_compare.py`；报告：`reports/replay-comparison.json`（脱敏；
未脱敏全量在 gitignored 的 `reports/interim/`）。28 个用例（意图 + WRITE 审批），真实主数据
按 `local-values.yaml`（gitignored）在槽位层代入。

### 结果：全部维度一致

| 维度 | 一致 |
|---|---|
| 能力选择（规则触发 ↔ SKOS 标签召回） | 28/28 |
| 缺槽/前置条件 | 26/26 |
| SHACL 参数校验 | 26/26 |
| WRITE 权限 duty | 7/7 |
| 与 eval expected 状态一致 | 26/26 |

WRITE 审批场景的权限结果：审批缺失/过期/版本不符/重复提交均正确拒绝（False）；
两条 success 与 sap-business-error 放行（True）——其中 **sap-business-error 权限成立但执行失败**，
正确体现"门禁 ≠ 执行结果"的分层。

### 过程中修复的问题

1. **SKOS 标签缺触发词**：codegen 只取 aliases，而 eval 语句实际包含 trigger/primary keywords
   （采购申请/应收/应付…）。已将纯文本强触发关键词并入 altLabel（regex 形关键词不收）；
2. **requireAny 分组前置**未在执行边界求值，已补；
3. 数值槽改用 `Decimal`（Python float 是 xsd:double，过不了 sh:datatype xsd:decimal）；
4. 失败状态识别纳入 gateway validate 失败；技术覆写拒绝路径（rfc-name 用例）按"语义存在、
   确定性守卫拦截"判定；
5. 明确了**比对海拔**：eval 显式声明 missingParameters 时以受治理契约为共同基准
   （原始引擎输出含 fact-satisfiable 入参，规划边界已调和）。

连续两次回放报告完全一致（可复现）。

## Task 5：资源与稳定性 — 已完成（2026-09-24）

脚本：`scripts/measure_resources.py`；报告：`reports/resource-measurement.json`（每查询 50 次采样）

| 指标 | 结果 |
|---|---|
| 图规模 | 648 triples（631 + SKOS 触发词 altLabel 17） |
| 图加载 | 19.3 ms |
| 进程内存（加载后峰值） | RSS 29.4 → 59.2 MB |
| validate 中位延迟 | 4.4 ms |
| preconditions 中位延迟 | 40.5 ms |
| permission 中位延迟 | 39.5 ms |
| recall 中位延迟 | 2.5 ms |

稳定性：

- 两次完整回放结果逐字节一致（REPLAY STABLE）；
- 两次资源测量结构一致，各查询中位延迟漂移 0.5–2.6%（<25% 阈值，MEASUREMENT STABLE）。

观察（影响 Phase 设计，非阻塞）：

- preconditions / permission 中位约 40ms，显著慢于 recall（2.5ms）——主因是每问一次都对图做
  SPARQL 解析；Phase 1 落地时应缓存查询计划/预编译，而非逐请求解析。

## Task 6：Go / No-Go 评审 — 已完成（2026-09-24）

报告：`reports/go-no-go-decision.md`

**决策：有条件 Go。** 方向成立（28 用例语义等价、低成本、可复现），但**不引入全量 Semantica
平台**——以 rdflib + pyshacl 自建等价轻量层；真正的可复用资产是 Task 2 的 codegen 与查询契约。
进入 Phase 1 的前置：Comet HEAVY 立项、codegen 提升为正式构建步骤、SPARQL 查询计划缓存、
resolve/enforce 边界保持。Semantica / EvoOntology 保留为未来能力升级时的评估对象。

## 任务总览

- [x] Task 1：环境 + 现有 OWL 加载验证
- [x] Task 2：bundle codegen（SKOS + SHACL），哈希可复现
- [x] Task 3：四类查询适配
- [x] Task 4：eval 回放双路径对比
- [x] Task 5：资源与稳定性
- [x] Task 6：Go / No-Go 评审材料
