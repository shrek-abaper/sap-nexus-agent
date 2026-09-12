# DSH Cross-Harness And Write Gate Specification

## Purpose

扩展自动化验证：in-process dsh 的 READ/WRITE 路径用 MockAdapter + 录制网关
端到端可测；跨 harness 一致性覆盖 SD/FI；WRITE 硬门（无审批零写、幂等、
subject 不被改）保持。

## Requirements

### Requirement: In-process dsh end-to-end tests with scripted model

系统 SHALL 提供 keyless 测试：MockAdapter 脚本驱动「选择工具→收到事实→回答」
与「提议补货→awaiting_approval→批准→action-receipt」两条链。

- **WHEN** 运行 dsh runtime 测试
  - **THEN** 不使用真实模型 key/网络，工具调用次数与选择的工具名可断言
- **WHEN** WRITE 链模拟用户批准
  - **THEN** 断言 approve 与 execute 各恰好一次、幂等重放 writeCount=1、
    审批前 execute 调用数为 0

### Requirement: Cross-harness parity extended to SD/FI

离线一致性 gate SHALL 增加销售订单与应收/应付的 golden 子集：相同录制网关响应
下，dsh facade 路径与 Python CLI 的槽位/能力链/fact 业务值相等。

- **WHEN** 运行扩展后的跨 harness gate
  - **THEN** MM（库存/PO）、SD（SO）、FI（AR 或 AP）至少各 1 例通过，全程无 SAP 连接
- **WHEN** 两侧业务值不一致
  - **THEN** gate 以记录化 diff 失败退出，不允许跳过

### Requirement: Write bypass regression guard

架构与契约测试 SHALL 锁定：harness/server 工具层无直连 Gateway/RFC/审批 token
路径；WRITE 唯一通道是服务端 prepare→decision→execute。

- **WHEN** 扫描 harness-dsh 与 harness-server 源码
  - **THEN** 无 `/capabilities/`、`BAPI_`、`X-SAP-Nexus-Approval-Token` 字面量
- **WHEN** 模型试图在未经 awaiting_approval 的情况下让 WRITE 工具执行
  - **THEN** 不发生 execute，测试断言零写
