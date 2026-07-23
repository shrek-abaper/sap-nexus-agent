# sap-nexus-agent-llm-intent-adapter 验证报告

## Summary

| 维度 | 结果 | 证据 |
|---|---|---|
| Completeness | PASS | `openspec instructions apply --change sap-nexus-agent-llm-intent-adapter --json` 显示 13/13 tasks complete |
| Correctness | PASS | `scripts/verify-agent-callplan-evidence.sh` 显示 38 passed, 1 skipped；Eval passed 7/7 |
| OpenSpec | PASS | `openspec validate --all --strict` 显示 3 passed, 0 failed |
| Live LLM smoke | PASS | 显式加载本地外部 `.env` 并设置 `SAP_NEXUS_LLM_LIVE=1` 后，`agent/tests/test_llm_live.py` 1 passed |
| Secret safety | PASS | 敏感信息扫描仅命中 `.env.example` 占位符、文档示例、redaction fixture 和测试假值；未发现真实 LLM key、SAP password 或 runtime trace |
| Branch handling | PASS | 项目规则要求当前分支直接工作；当前在 `main`，未创建开发分支，分支处理按 no-op handled |

## Verification Commands

```bash
COMET_ENV="${COMET_ENV:-$(find . "$HOME"/.*/skills "$HOME/.config" "$HOME/.gemini" -path '*/comet/scripts/comet-env.sh' -type f -print -quit 2>/dev/null)}"
. "$COMET_ENV"
"$COMET_BASH" "$COMET_STATE" check sap-nexus-agent-llm-intent-adapter verify
"$COMET_BASH" "$COMET_STATE" scale sap-nexus-agent-llm-intent-adapter
```

Result:

```text
ALL CHECKS PASSED — ready to proceed
verify_result=pending
verify_mode=full
```

```bash
scripts/verify-agent-callplan-evidence.sh
```

Result:

```text
38 passed, 1 skipped in 0.05s
Eval passed: 7/7
Totals: 3 passed, 0 failed (3 items)
```

```bash
openspec validate --all --strict
```

Result:

```text
✓ spec/agent-callplan-evidence
✓ spec/capability-registry-gateway
✓ change/sap-nexus-agent-llm-intent-adapter
Totals: 3 passed, 0 failed (3 items)
```

Note: OpenSpec emitted PostHog network flush errors after successful validation output. Per project instructions, these telemetry flush errors are non-blocking when the command exits successfully and validation totals pass.

```bash
.venv/bin/python -c "from dotenv import load_dotenv; from pathlib import Path; import os, pytest; load_dotenv(Path('cbu-brain-agent/.env'), override=True); os.environ['SAP_NEXUS_LLM_LIVE']='1'; raise SystemExit(pytest.main(['agent/tests/test_llm_live.py','-q']))"
```

Result:

```text
1 passed in 1.43s
```

The live smoke command used only local environment loading and did not print API keys, model gateway config, SAP destination config, or raw model response.

```bash
rg -n "(LLM_API_KEY=|sk-[A-Za-z0-9_-]{10,}|SAP_PASSWORD=|password\s*[:=]|api_key\s*=\s*['\"][^*]|base_url\s*=\s*['\"]https?://)" --glob '!runtime/**' --glob '!.venv/**' --glob '!node_modules/**' --glob '!*.pyc' .
```

Result: only placeholders, documentation examples, redaction fixtures, and fake test values were found.

## Requirement Mapping

| Requirement | Status | Evidence |
|---|---|---|
| Real OpenAI-compatible LLM adapter | PASS | `agent/sap_nexus_agent/llm_client.py` loads `LLM_*` settings and calls `chat.completions.create` with JSON response format |
| `hybrid` default with rule fallback | PASS | `agent/sap_nexus_agent/cli.py` defaults `--intent-mode hybrid`; `agent/sap_nexus_agent/llm_intent.py` falls back on unavailable or untrusted LLM output |
| Closed-set `MM.Inventory.GetAvailability` only | PASS | `llm_intent.py` rejects unknown capability IDs before downstream capability selection |
| Do not allow LLM-generated `rfcName` | PASS | `llm_intent.py` marks `rfcName` output untrusted; hybrid independently falls back to rules, and direct LLM result is blocked before Gateway |
| Missing `material` or `plant` clarifies before Gateway | PASS | `agent/tests/test_llm_intent.py` and `agent/tests/test_orchestrator.py` cover missing plant without Gateway calls |
| Normal verification requires no live LLM credentials | PASS | `agent/tests/test_llm_live.py` skips unless `SAP_NEXUS_LLM_LIVE=1` |
| No SAP write / recommendation / KG runtime / UI scope creep | PASS | No new write action, `RecommendationPlan`, KG runtime, UI, or arbitrary RFC execution code was added |

## Code Review Notes

- No CRITICAL issues found.
- No IMPORTANT issues found.
- Follow-up fixed during verify: hybrid now falls back to the rule parser when LLM output is untrusted, `llm` mode returns a structured unsupported parse result on LLM unavailability instead of raising through the CLI path, and `LlmSettings.__repr__` redacts both API key and base URL.
- `LLM_MAX_RETRIES` is now passed to the OpenAI-compatible client constructor instead of being only loaded.

## Final Assessment

All checked tasks, requirements, tests, evals, OpenSpec validation, live LLM smoke, and secret-safety checks passed. The change is ready to advance to the Comet archive confirmation gate.
