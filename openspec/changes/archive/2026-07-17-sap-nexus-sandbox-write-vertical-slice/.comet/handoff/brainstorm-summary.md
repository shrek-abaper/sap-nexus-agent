# Brainstorm Summary - sap-nexus-sandbox-write-vertical-slice

- Change: sap-nexus-sandbox-write-vertical-slice
- Phase: design
- Status: 已定稿 (2026-07-16)
- 上一产物: proposal.md / design.md (open 阶段高层框架)

## 澄清决策记录

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| 1 | Agent approval 交互流 | 方案 A: Workbench Console HITL 审批按钮 | 复用现有 HITL 状态机骨架, 最贴量产形态, live smoke 可视化 |
| 2 | ApprovalRecord 存储 | JSONL trace 为权威存储 + Markdown 为 HITL 展示派生视图 | 两个正交关注点分离: 落盘/回放走 JSONL, 可读性走 Markdown 渲染 |
| 3 | approval TTL | 默认 10 分钟, 可配置 (SAP_NEXUS_APPROVAL_TTL_SECONDS, 默认 600) | HITL 即时确认语义, 降低审批与执行间业务状态漂移 |
| 4 | BAPI_PR_CREATE 字段集 | 单 capability + 可选 acct_assgn_cat (默认空=直采) / cost_center (条件必填) | 间采是 PR 类型自然分支, 不拆两个 capability; 默认实物直采 |
| 4a | 间采类型支持范围 | 薄纵切先只支持 acct_assgn_cat="K" (成本中心) | 够验证间采分支即可, 其他类型 ("F" 订单等) 留后续 |
| 4b | PR 号提取 | PRITEMEXP.PREQ_NO (整单号), RETURN 成功消息辅助校验 | 整单号最可靠 |

## 已确认 Design 五节

1. **架构与数据流**: 用户 -> Agent(intent 缺参澄清 -> Action CallPlan + ApprovalRecord pending) -> JSONL trace 落盘 + Markdown HITL 渲染 -> Workbench 审批卡片 -> 用户批准 (approved) -> Gateway(approval 守卫 -> JCo WRITE execute BAPI_PR_CREATE -> commit/rollback 守卫) -> SAP PR 凭证 -> ActionResult -> Agent executed -> Narrator
2. **组件与职责边界**: ApprovalGuard(守卫, 不碰 SAP) / JcoCapabilityExecutor write 分支(BAPI+commit/rollback, 不碰 approval) / approval.py(状态机+快照, 不碰 Gateway) / Workbench HITL 卡片(展示交互, 不直接调 SAP) -- 每单元可独立测试
3. **capability 契约**: MM.PR.CreateDraft, kind=Action, sideEffect=sap_write, requiresApproval=true, 7 inputs(5 必填 + acct_assgn_cat 可选 + cost_center 条件必填), output prNumber/returnMessages
4. **错误处理**: 8 种失败场景矩阵(approval 4 种 + SAP 业务错误 + commit 失败 + 参数澄清 2 种) + 成功; commit/rollback 时序参考 STO create; duplicate submit 进程内索引 + trace 兜底
5. **测试策略**: 单元(mock) + 契约(schema) + Eval 回归(9 case) + Live smoke(本地 .env, 直采+间采各 1)

## 关键约束

- READ/WRITE 隔离: Function 永不 commit, Action 必经 approval 守卫才 commit
- commit/rollback 在 JcoCapabilityExecutor write 分支内部强制 (Agent/外部不触发)
- approval 守卫在 Gateway execute 入口、SAP 调用前 fail-closed
- 敏感数据守卫不变: .env/SAP 凭据/destination/token 不进 trace/响应/日志
- 仅 sandbox/dev client, 禁止生产 client

## 待 Design Doc 细化(已在 Design Doc 覆盖)

- BAPI_PR_CREATE PRITEM 具体字段映射 (design 第 3 节已定)
- approval TTL 默认值 (600s, design 第 1 节已定)
- ApprovalRecord 存储方式 (JSONL trace, design 第 1/2 节已定)
