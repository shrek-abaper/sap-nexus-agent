"""Paid-model goal interpreter: produces ONLY an untrusted SemanticGoalDraft.

Security model: the model sees semantic vocabulary derived from the pinned
release (fact types, allowlisted fields, four operators) and receives no
credentials, RFC names, URLs, or technical bindings. Its output goes through
the same strict draft validation as every other entry; the model never
selects capabilities or executes anything.
"""

from __future__ import annotations

from typing import Any

from .draft_validation import validate_draft


class ModelInterpreterError(RuntimeError):
    """The paid model could not provide a structurally acceptable draft."""


_SYSTEM_TEMPLATE = """你是 SAP Nexus 本体约束只读分析的"目标解释器"。
你的唯一任务：把用户问题转成 SemanticGoalDraft v1 JSON 对象，不要输出任何其他文字。

# 允许请求的事实类型与字段（不得使用其他字段）
{fact_table}

# 对象选择器 objectSelectors
- 物料：{{"objectTypeId":"sapnexus:Material","key":"material","value":"<物料号>"}}
- 工厂：{{"objectTypeId":"sapnexus:Plant","key":"plant","value":"<工厂>"}}

# 分析算子 analysisNodes（只有这 4 个，不得新增）
- select_fields：params.fields 为允许字段名列表
- filter_eq：params 为 field/value 等值过滤（如指定供应商）
- group_sum：params = dimensions（分组字段，如 supplier）、measure（只能是 orderQuantity）、unitField（只能是 purchaseOrderUnit）
- compare：只允许同口径、同单位的数值比较；输入只能引用允许字段或上游节点

# 约束 constraints
来源只能是 explicitUser 或 confirmedContext；name/semanticType/value 字符串。

# 口径铁律
- orderQuantity 是采购订单订购量，绝不代表"到货量/在途/ATP/承诺交期"。
- 本发布不存在交期、收货数量、需求预测、ATP 相关字段；用户问到这些时，仍只允许使用上表字段，
  由下游判定语义缺口，严禁编造字段。
- 不得出现 RFC、binding、URL、路径、SQL、凭据、可执行代码等任何技术性键或值。
- 只读：不得提出任何写入或采购申请创建类结论。

# 输出格式（严格 JSON，键固定）
{{
  "schemaVersion": 1,
  "requestedFacts": [{{"factTypeId": "...", "fields": ["..."], "objectSelectors": [...]}}],
  "constraints": [],
  "analysisNodes": [{{"nodeId":"a1","operatorId":"group_sum",
    "inputs":[{{"kind":"factField","factTypeId":"sapnexus:PurchaseOrderSupplyFact","field":"orderQuantity"}}],
    "params":{{"dimensions":["supplier"],"measure":"orderQuantity","unitField":"purchaseOrderUnit"}},
    "dependsOn":[]}}],
  "requestedConclusions": [{{"id":"c1","statement":"<结论的中性描述>","evidenceRequirement":"<证据要求>"}}],
  "assumptions": []
}}
"""


def build_system_prompt(pinned: Any) -> str:
    lines = []
    for fact_type in sorted(pinned.allowlist_fields):
        fields = ", ".join(sorted(pinned.allowlist_fields[fact_type]))
        lines.append(f"- {fact_type}: {fields}")
    return _SYSTEM_TEMPLATE.format(fact_table="\n".join(lines))


class ModelGoalInterpreter:
    """Interprets a user utterance into a draft via an OpenAI-compatible LLM."""

    def __init__(self, pinned: Any, client: Any | None = None, max_tokens: int = 1200):
        self._pinned = pinned
        self._max_tokens = max_tokens
        self.call_count = 0
        self._client = client

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        from ..llm_client import LlmUnavailable, OpenAiCompatibleLlmClient

        try:
            self._client = OpenAiCompatibleLlmClient()
        except LlmUnavailable:
            raise ModelInterpreterError("MODEL_UNAVAILABLE")
        return self._client

    def interpret(
        self,
        request: dict[str, Any],
        vocabulary: Any = None,
        feedback: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        utterance = str(request.get("utterance") or request.get("question") or "")
        messages: list[dict[str, str]] = [
            {"role": "system", "content": build_system_prompt(self._pinned)},
            {"role": "user", "content": utterance},
        ]
        if feedback:
            import json

            messages.append({
                "role": "user",
                "content": (
                    "上一版草案未通过校验，请只修复以下问题后重新输出完整 JSON，"
                    f"不得改变问题的业务口径：\n{json.dumps(feedback, ensure_ascii=False)}"
                ),
            })
        client = self._resolve_client()
        try:
            document = client.chat_json(
                messages, temperature=0.0, max_tokens=self._max_tokens
            )
        except Exception as exc:  # noqa: BLE001 - boundary: normalize all LLM failures
            raise ModelInterpreterError(f"MODEL_UNAVAILABLE:{exc}") from exc
        self.call_count += 1

        if not isinstance(document, dict):
            raise ModelInterpreterError("MODEL_OUTPUT_NOT_OBJECT")
        # Cheap local guard before returning; the authoritative validation is
        # the shared draft pipeline (which also feeds repair feedback).
        report = validate_draft(document, self._pinned)
        if not report.valid and feedback is not None:
            # Second attempt still invalid: surface for the pipeline terminal.
            return document
        return document
