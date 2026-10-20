# Master-Data Entity Resolution (PostgreSQL Projection)

本体驱动的主数据实体解析：用户在聊天中给出不完整描述，系统从这个**只读检索投影**搜索真实候选，消歧确认后把真实编码绑定到业务能力的参数。PostgreSQL 不是第二套主数据权威源；SAP 属性只能经快照导入器写入。

## 组件

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| 逻辑规则 | `ontology/entity-resolution.yaml` | 对象身份、可搜索/展示字段、确认策略、参数绑定（无凭据、无物理表名） |
| 物理映射 | `master-data/physical-mappings.yaml` | queryTemplateId → 视图/列白名单（服务端可信配置，不生成 SQL） |
| PG schema | `db/migrations/0001_master_data.sql`（对象）/ `0002_master_data_roles.sql`（只读角色，需管理员） | 快照注册表、实体/描述/别名/组织范围、当前快照视图、pg_trgm 索引 |
| 导入器 | `agent/sap_nexus_agent/master_data/importer.py` | 批次校验、干跑、单事务原子发布、幂等、仅 full snapshot |
| Python Provider | `agent/sap_nexus_agent/master_data/provider.py` | 固定参数化查询、检索顺序、错误分型（测试/离线参考实现） |
| Java TechnicalAdapter | `services/gateway/masterdata/` | `PG_MASTERDATA_READ` executor，治理链内的生产路径 |
| 编排层 | `agent/sap_nexus_agent/entity_resolution/` | ResolvedEntityRef 证据、ENTITY_CHOICE 协议、确定性选择解析 |

## 本地启动（开发）

```bash
# 1. 安装（一次性，需要 sudo）
sudo apt install -y postgresql postgresql-contrib

# 2. 启动并建库（一次性）
sudo service postgresql start
sudo -u postgres createuser --createdb "$USER"
createdb sap_nexus_dev

# 3. 迁移
psql -d sap_nexus_dev -f db/migrations/0001_master_data.sql
sudo -u postgres psql -d sap_nexus_dev -f db/migrations/0002_master_data_roles.sql

# 4. 只读登录角色（Gateway JDBC 用；密码经 read -s 输入，只写入 .env）
read -s -p "md_search password: " MD_PW && echo && \
sudo -u postgres psql -c "CREATE ROLE md_search LOGIN PASSWORD '$MD_PW' IN ROLE md_search_ro;" && \
{ echo "PG_MASTERDATA_USER=md_search"; echo "PG_MASTERDATA_PASSWORD=$MD_PW"; } >> .env && \
unset MD_PW

# 5. 导入合成示例数据（三类对象 + 替换用 v2）
PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.master_data.importer master-data/fixtures/materials-v1.json
PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.master_data.importer master-data/fixtures/customers-v1.json
PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.master_data.importer master-data/fixtures/suppliers-v1.json
# 干跑（不发布）：加 --dry-run
```

凭据永远走 `.env`（gitignored）或 peer 认证；`.env.example` 只有占位符。

## 测试

```bash
# 真实 PG 集成测试（独立 sap_nexus_test 库，自动建库/迁移/导入）
PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_master_data_pg.py -q

# 编排/协议/安全回归（FakeGateway，无需 PG）
PYTHONPATH=agent .venv/bin/python -m pytest agent/tests/test_entity_resolution_orchestration.py agent/tests/test_entity_resolution_parties.py agent/tests/test_entity_resolution_security.py -q

# Gateway（Java，含 PG_MASTERDATA_READ adapter 单测）
cd services/gateway && ./gradlew test

# 受控链路冒烟（真实 PG 经 Gateway）
cd services && env $(grep -E '^PG_MASTERDATA_' ../.env | grep -v PASSWORD | xargs) \
  PG_MASTERDATA_PASSWORD=$(grep '^PG_MASTERDATA_PASSWORD=' ../.env | cut -d= -f2-) \
  java -jar gateway/app/build/libs/app-0.1.0-SNAPSHOT.jar &
curl --noproxy '*' -X POST http://127.0.0.1:8080/capabilities/MD.Material.Search/execute \
  -H 'Content-Type: application/json' \
  -d '{"parameters":{"query":"蓝色耐高温密封圈","plant":"1000"}}'
```

## 运行时开关

- `ENTITY_RESOLUTION_MODE=on|off`（默认 **off**）：关闭时旧编码路径行为完全保持，不发起任何主数据检索。DSH/agent-run 的 Python 子进程继承 `.env`。
- `PG_MASTERDATA_JDBC_URL/USER/PASSWORD/MAPPINGS_PATH`：Gateway 连接配置（环境注入）。
- `SAP_NEXUS_MD_DSN` / `SAP_NEXUS_MD_DBNAME`（默认 `sap_nexus_dev`）：Python 导入器/Provider 连接。
- `SAP_NEXUS_MD_TEST_DBNAME`（默认 `sap_nexus_test`）：集成测试库。

## 日常维护（maintain CLI）

不直接 UPDATE 表：每次编辑读取当前 active 快照 → 内存中应用变更 → 经 `import_snapshot` 发布**新的 full snapshot**（默认干跑，`--apply` 才发布）。校验、原子发布、幂等、回滚到上一快照的保证全部继承。

```bash
M="PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.master_data.maintain"

$M list sapnexus:Material                 # 当前快照实体一览（状态/描述/属性/组织范围）
$M show sapnexus:Material DEMOA1          # 单个实体详情（JSON）
$M upsert sapnexus:Material DEMOX1 \
    --name-zh "丁腈密封垫 3mm" \
    --attr materialGroup=GASKET --attr sizeDimension=3mm --attr baseUnitOfMeasure=EA \
    --org plant=1000 --apply              # 新增或更新（属性合并，非覆盖）
$M deactivate sapnexus:Customer C10001 --apply   # 停用（候选中消失，get-by-key 仍可见状态）
$M activate sapnexus:Customer C10001 --apply     # 恢复
$M remove sapnexus:Supplier V90000 --apply       # 从下一快照移除
$M export sapnexus:Material backup-materials.json  # 导出当前快照（回滚/审计输入）
```

- 编辑语义：`upsert` 合并属性/别名/组织范围（不丢未提及字段）；`--name-zh` 自动成为唯一 official 描述。
- `--source-time` 记录来源提取时间；缺省如实记 unknown，不用导入时间冒充。
- 非法输入（未声明属性、缺失 official 描述等）整批拒绝，不部分发布。
- 回滚误操作：`export` 的文件可经 importer 重新导入，或用快照 status 翻转（见下节）。

## 快照语义与回滚

- 仅支持 **full snapshot**；incremental 批次被明确拒绝。批次重复导入幂等（内容哈希去重）。
- 发布 = 单事务：新快照 `loading` → 数据写入 → 旧快照 `superseded` → 新快照 `active`。读者只见 `active`；失败回滚后上一有效快照继续服务。
- full snapshot 只替换**声明覆盖范围**（同 source_system/client/object_type）；其他系统/对象类型的快照不受影响。
- **回滚**：`UPDATE md.snapshot SET status='active' WHERE snapshot_id='<old>'; UPDATE md.snapshot SET status='superseded' WHERE snapshot_id='<new>';`（同一事务内执行）；语义版本（ontology/registry）回滚走 git。
- 失效/删除的对象随快照替换消失；`status='inactive'` 实体不出现在候选中，get-by-key 仍返回其状态以区分"不存在"。

## 已知边界（v1）

- HANA Adapter **未实现**；接入 HANA 需要：新 Provider/Adapter（同一窄契约）、物理映射文件、凭据授权，本体规则/导入契约/协议层不变。
- 可选槽位（如 `SD.SalesOrder.GetList.customerNumber`）v1 不触发解析（需要意图信号）；`customerNumber` 绑定映射已在契约层验证。
- 当前 principal 为 sandbox placeholder；生产身份授权未实现。Java 侧 `callerContext.masterDataScope` 由服务端注入点预留。
- 性能证据仅覆盖 15 实体合成数据集（WSL2，PG 16.15）：子串 p50≈3ms；trigram GIN 索引在该规模未被优化器选用（EXPLAIN 已记录），更大规模需重测。生产 p95/并发/费用预算：**待确认**。
