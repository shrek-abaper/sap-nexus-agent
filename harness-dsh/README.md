# sap-nexus-harness-dsh

DeepSeek Harness（dsh）形态的 SAP Nexus 可替换 harness 层。它只承担 LLM 调用、
T-A-O 循环与结果呈现；语义解析、编排、权限判定与 SAP 执行全部在服务端（Next app
的 semantic-tool facade → 既有治理链 → Java Gateway）。本进程内没有任何直连
Gateway / RFC / 绑定 / 凭证的调用面（`tests/architecture.test.ts` 锁定）。

## 边界

- 模型可见的唯一业务工具：`diagnose_material_supply`（READ 复合语义工具），
  对应服务端 `POST /api/semantic-tools`。
- 工具的 pre-execute 只做本地形状校验与遥测（stderr JSONL）；服务端契约是唯一
  权威校验。
- 不挂载 bash/fs/subagent/workflow 等 coding-agent 面（见
  `config/cordis.bundle.patch.yml`）。
- dev-only：不接 live SAP；一致性验证全程离线 fixture。

## 版本 pin（preview 期硬要求）

所有 `@deepseek-ai/dsh-*` 包精确钉在 **0.1.5-rc.1**（package.json `dependencies`
与 `overrides`，lockfile 中无 rc.2 漂移）；`@deepseek-ai/cordis` 钉 4.0.2。
任何 dsh 包升级都是独立变更评审，禁止 `^`/`~`/`latest`。

## 三层配置

| 层 | 文件 | 作用 |
| --- | --- | --- |
| bundle | `config/cordis.bundle.patch.yml` | 随包评审：spine 条目、provider、工具插件 |
| profile root | `config/cordis.yml` | 空锚点（dsh profile 约定） |
| overlay | `config/cordis.patch.yml` | 本机 dev 覆盖（行级整值替换） |

导出审计：

```bash
npm run build
npm run dump-config   # 不 boot、不求值 !!js，逐段标注来源文件
```

## 运行

```bash
npm ci
npm run build
cp .env.example .env   # 填入 OpenAI-compatible 端点与 key；同时启动 facade 所在的 Next app
npm start -- "A100 在 1000 工厂够不够用、在途多少？"
```

环境变量：`SAP_NEXUS_LLM_PROVIDER`（默认 sapnexus）、`SAP_NEXUS_LLM_MODEL`
（默认 deepseek-chat）、`SAP_NEXUS_LLM_BASE_URL`、`SAP_NEXUS_LLM_API_KEY`、
`SAP_NEXUS_FACADE_URL`（默认 http://127.0.0.1:3000）、
`SAP_NEXUS_FACADE_TIMEOUT_MS`。

## 测试

```bash
npm test          # vitest：脚本化 mock LLM 的工具往返 / facade 客户端 / 架构红线
```

模型驱动往返用 keyless `MockAdapter`（`tests/mock-llm.ts`）+ 本地 fixture HTTP
facade，不产生真实模型或 SAP 调用。
