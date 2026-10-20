# 实体解析逻辑契约与本体映射

## 概念分离

`EntityMention`（用户描述）、`Entity`（数据库实体）、`EntityCandidate`（搜索候选）、`ResolvedEntityRef`（已解析引用）分开建模，互不混用。

模型可产生待验证 mention、目标对象建议与选择意图；规范编码只能来自受治理数据访问与验证。

## 本体声明（ontology/entity-resolution.yaml）

每个逻辑对象至少声明：`objectTypeId`、标识符 semanticType、逻辑标识字段与显示名称字段、可搜索的描述/别名/区分属性、支持的组织过滤与语言维度、对应注册搜索能力、精确/模糊匹配确认策略、候选展示字段与输出契约。

Material、Customer、Supplier 的参数绑定经 capability input 的 semanticType 加显式映射实现，不按字符串包含判断。

object-types.yaml 补齐 Customer 对象类型，与 `sapnexus:CustomerNumber` 对齐；同一 Customer 引用按声明映射到 `customer`（FI.AR.GetOpenItems）与 `customerNumber`（SD.SalesOrder.GetList）；Supplier 映射 `vendor`。

## 物理映射

物理映射描述逻辑字段到白名单关系/视图/列的对应，仅由服务端 Adapter 消费。SQL 方言、查询模板、索引实现留在 Provider。

映射文件属可信配置，用户与 LLM 不可改表名/列名；连接凭据不进入本体文件。采用"规范化视图 + 固定查询"或"schema 校验 + 白名单字段映射"中更简单可审计的一种，不建通用 ORM/查询编译器。

## 发布与校验

规则引用的对象类型、semanticType、capability、输出字段必须存在且类型一致，由 schema/validator 强制。

搜索能力只读，不带 SAP 写副作用或审批需求。展示字段必须真实来自返回契约，禁止模型补造规格、城市、名称。

身份键不能为空；同名描述不可用作唯一身份。新增规则纳入 SemanticRelease 显式源清单（SEMANTIC_SOURCE_MANIFEST / ASSET_SCHEMAS）及一致性校验。

数据版本与语义版本分离；主数据导入不要求发布本体。schema/配置变化使未完成旧选择失效，或经显式兼容规则重新验证。
