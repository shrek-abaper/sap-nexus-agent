"""Unit tests for ConversationContext data model (Task 1)."""

from sap_nexus_agent.conversation_context import (
    ConversationContext,
    LastContext,
    Turn,
)


def test_last_context_clarify_round_trip():
    ctx = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2"},
        missing_parameters=["plant"],
        decision_type="CLARIFY",
    )
    payload = ctx.to_dict()
    assert payload == {
        "capabilityId": "MM.Inventory.GetAvailability",
        "parameters": {"material": "DEMOA2"},
        "missingParameters": ["plant"],
        "decisionType": "CLARIFY",
    }
    assert LastContext.from_dict(payload) == ctx


def test_last_context_select_empty_missing():
    ctx = LastContext(
        capability_id="MM.Inventory.GetAvailability",
        parameters={"material": "DEMOA2", "plant": "1000"},
        missing_parameters=[],
        decision_type="SELECT",
    )
    assert ctx.missing_parameters == []
    assert ctx.decision_type == "SELECT"


def test_turn_to_dict():
    turn = Turn(role="user", content="DEMOA2 1000")
    assert turn.to_dict() == {"role": "user", "content": "DEMOA2 1000"}


def test_conversation_context_round_trip():
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=(Turn(role="user", content="查库存"), Turn(role="assistant", content="请提供物料和工厂")),
    )
    payload = ctx.to_dict()
    restored = ConversationContext.from_dict(payload)
    assert restored == ctx


def test_conversation_context_empty_round_trip():
    ctx = ConversationContext(last_context=None, history=None)
    payload = ctx.to_dict()
    assert payload == {"lastContext": None, "history": None}
    assert ConversationContext.from_dict(payload) == ctx


# ---------------------------------------------------------------------------
# Task 2: IntentAdapter signature extension (single-turn regression)
# ---------------------------------------------------------------------------

from dataclasses import dataclass  # noqa: E402

from sap_nexus_agent.intent import parse_intent  # noqa: E402
from sap_nexus_agent.orchestrator import run_query  # noqa: E402
from sap_nexus_agent.gateway_client import GatewayClientProtocol  # noqa: E402
from sap_nexus_agent.match_decision import MatchDecision, MatchedIntent  # noqa: E402


@dataclass
class _FakeGateway:
    validate_result: object = None
    execute_result: object = None
    def validate(self, cap_id, params): return self.validate_result
    def execute(self, cap_id, params, **kwargs): return self.execute_result
    def approve(self, cap_id, record): pass


def test_parse_intent_context_none_unchanged():
    """context=None 时 parse_intent 行为与单轮完全一致（回归测试）。

    Note: brief 原文断言 ``result.capability_id == "MM.Inventory.GetAvailability"``
    与 ``result.parameters["plant"] == "1000"`` 与现有 ``parse_intent`` 行为不符
    （single-intent 路径顶层 ``capability_id`` 保持 None，仅 ``matched_intents[0].capability_id``
    被填充；``"库存 DEMOA2 1000"`` 不匹配工厂提取模式，plant 进入 missing）。
    此处改为断言实际行为，保持"context=None 行为不变"的回归意图。
    """
    result = parse_intent("库存 DEMOA2 1000")
    assert result.intent == "inventory_availability"
    assert result.parameters["material"] == "DEMOA2"
    assert "plant" not in result.parameters
    assert result.missing_parameters == ["plant"]
    assert result.capability_id is None
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"


def test_parse_intent_context_passed_but_ignored_in_task2():
    """Task 2 阶段 context 非 None 时仍走单轮（sticky 在 Task 3 实现）。

    本测试验证：(1) 签名接受 context 参数不报错；(2) Task 2 阶段 context 被忽略，
    结果与 ``context=None`` 完全一致。
    """
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=None,
    )
    text = "库存 DEMOA2 1000"
    result_with_ctx = parse_intent(text, context=ctx)
    result_without_ctx = parse_intent(text)
    assert result_with_ctx == result_without_ctx


def test_run_query_context_none_backward_compatible(monkeypatch):
    """run_query(context=None) 与现有签名完全兼容。"""
    @dataclass
    class VResult:
        success: bool = True
        trace_id: str = "t"
        capability_id: str = "MM.Inventory.GetAvailability"
        error_type: str = "NONE"
        messages: list = None
        def __post_init__(self):
            if self.messages is None:
                self.messages = []
    @dataclass
    class EResult:
        success: bool = True
        trace_id: str = "t"
        capability_id: str = "MM.Inventory.GetAvailability"
        error_type: str = "NONE"
        executor: dict = None
        return_messages: list = None
        data: dict = None
        duration_ms: int = 1
        def __post_init__(self):
            if self.executor is None:
                self.executor = {}
            if self.return_messages is None:
                self.return_messages = []
            if self.data is None:
                self.data = {"availableQuantity": 7}
    gateway = _FakeGateway(validate_result=VResult(), execute_result=EResult())
    outcome = run_query("库存 DEMOA2 1000", gateway, context=None)
    assert outcome.status in {"success", "clarification"}
