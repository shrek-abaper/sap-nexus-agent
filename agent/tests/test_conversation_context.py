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


# ---------------------------------------------------------------------------
# Task 3: sticky continuation algorithm
# ---------------------------------------------------------------------------


def _catalog():
    """Load the real intent catalog from registry/capabilities.yaml.

    Uses the file-location resolver (no ``repo_root``) so the catalog is found
    regardless of pytest's cwd; this matches how production code
    (``parse_intent`` wiring, ``build_intent_adapter``) loads the catalog.
    """
    from sap_nexus_agent.registry_loader import load_intent_catalog

    return load_intent_catalog()


def test_contains_any_primary_keyword_inventory():
    """Primary keyword detection: inventory & PO keywords hit; pure params miss."""
    from sap_nexus_agent.llm_intent import _contains_any_primary_keyword

    assert _contains_any_primary_keyword("查一下库存") is True
    assert _contains_any_primary_keyword("采购订单列表") is True
    assert _contains_any_primary_keyword("DEMOA2 1000") is False  # 纯参数，无主关键词


def test_sticky_clarify_fills_plant():
    """turn1 CLARIFY 缺 plant；turn2 补 plant -> missing 缩减为 []。

    Note: ``_extract_plant`` requires a ``在 <code>`` prefix or ``<code> 工厂``
    suffix (existing extractor behavior; bare ``1000`` returns None). The
    follow-up utterance uses ``在 1000`` - a natural response to the CLARIFY
    prompt ``请提供要查询的工厂`` - so the extractor can parse the plant.
    """
    from sap_nexus_agent.llm_intent import resolve_with_context

    catalog = _catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=None,
    )
    result = resolve_with_context("在 1000", ctx, catalog)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters["material"] == "DEMOA2"
    assert result.parameters["plant"] == "1000"
    assert result.missing_parameters == []


def test_sticky_clarify_partial_still_missing():
    """turn2 补了一个参数但仍缺另一个 -> CLARIFY 缩减。"""
    from sap_nexus_agent.llm_intent import resolve_with_context

    catalog = _catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={},
            missing_parameters=["material", "plant"],
            decision_type="CLARIFY",
        ),
        history=None,
    )
    result = resolve_with_context("DEMOA2", ctx, catalog)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    assert result.parameters["material"] == "DEMOA2"
    assert "plant" not in result.parameters
    assert result.missing_parameters == ["plant"]


def test_sticky_select_inherits_capability_q1():
    """Q1=覆盖：SELECT 后追问'换一个 DEMOA4' 继承 inventory + plant。"""
    from sap_nexus_agent.llm_intent import resolve_with_context

    catalog = _catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2", "plant": "1000"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    result = resolve_with_context("换一个 DEMOA4", ctx, catalog)
    assert result.capability_id == "MM.Inventory.GetAvailability"
    # 新参数覆盖旧，未提供保留
    assert result.parameters["material"] == "DEMOA4"
    assert result.parameters["plant"] == "1000"
    assert result.missing_parameters == []


def test_sticky_primary_keyword_overrides():
    """turn2 含主关键词 -> 新轮覆盖 last_context。

    Note (Task 2 concern 1): parse_intent single-intent 路径不设顶层
    ``capability_id`` (值为 None)，仅 ``matched_intents[0].capability_id`` 有值。
    故断言 ``matched_intents[0].capability_id`` 而非顶层。
    """
    from sap_nexus_agent.llm_intent import resolve_with_context

    catalog = _catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            parameters={"material": "DEMOA2"},
            missing_parameters=["plant"],
            decision_type="CLARIFY",
        ),
        history=None,
    )
    result = resolve_with_context("采购订单 4500000001", ctx, catalog)
    # 主关键词触发新轮，走 parse_intent，不继承 inventory
    assert result.capability_id is None
    assert result.matched_intents[0].capability_id == "MM.PurchaseOrder.GetList"


def test_sticky_none_context_falls_back_to_single_turn():
    """context=None -> resolve_with_context 退化为单轮 parse_intent。"""
    from sap_nexus_agent.llm_intent import resolve_with_context

    catalog = _catalog()
    result = resolve_with_context("库存 DEMOA2 1000", None, catalog)
    # 单轮路径：顶层 capability_id 为 None (Task 2 concern 1)
    assert result.intent == "inventory_availability"
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"


def test_sticky_none_last_context_falls_back_to_single_turn():
    """last_context=None -> 退化为单轮 parse_intent。"""
    from sap_nexus_agent.llm_intent import resolve_with_context

    catalog = _catalog()
    ctx = ConversationContext(last_context=None, history=None)
    result = resolve_with_context("库存 DEMOA2 1000", ctx, catalog)
    assert result.intent == "inventory_availability"
    assert result.matched_intents[0].capability_id == "MM.Inventory.GetAvailability"


def test_sticky_unknown_capability_falls_back_to_single_turn():
    """last_context.capability_id 不在 catalog -> 退化为单轮（防御降级）。"""
    from sap_nexus_agent.llm_intent import resolve_with_context

    catalog = _catalog()
    ctx = ConversationContext(
        last_context=LastContext(
            capability_id="MM.Nonexistent.Capability",
            parameters={"material": "DEMOA2"},
            missing_parameters=[],
            decision_type="SELECT",
        ),
        history=None,
    )
    # 文本不含主关键词，但 capability_id 未注册 -> 应降级为单轮
    result = resolve_with_context("DEMOA2 1000", ctx, catalog)
    # 单轮路径：inventory 匹配 (含 "库存"? 否。但文本无主关键词 -> 单轮 parse_intent 返回 unknown)
    # 实际：parse_intent("DEMOA2 1000") 无任何主关键词 -> unknown intent
    assert result.intent is None
    assert result.matched_intents == []
