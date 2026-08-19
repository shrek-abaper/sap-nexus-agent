import time

from sap_nexus_agent.extraction import clarify
from sap_nexus_agent.extraction.clarify import render_clarify
from sap_nexus_agent.llm_intent import parse_with_hybrid
from sap_nexus_agent.registry_loader import load_intent_catalog


def _cap(cap_id):
    catalog = load_intent_catalog()
    cap = catalog.find(cap_id)
    assert cap is not None and cap.intent_config is not None
    return cap


def test_inventory_cases_exact_missing_sets():
    inv = _cap("MM.Inventory.GetAvailability")
    assert render_clarify(inv, ["material"]) == "请提供要查询的物料编号。"
    assert render_clarify(inv, ["plant"]) == "请提供要查询的工厂。"
    assert render_clarify(inv, ["material", "plant"]) == "请提供要查询的物料编号和工厂。"
    assert render_clarify(inv, []) is None


def test_pr_fallback_join_template():
    pr = _cap("MM.PR.CreateDraft")
    assert render_clarify(pr, ["quantity", "unit"]) == "请提供: 数量, 单位"
    assert render_clarify(pr, ["material", "plant"]) == "请提供: 物料编号, 工厂"


def test_missing_locale_falls_back_to_names():
    pr = _cap("MM.PR.CreateDraft")
    # no en-US entry declared -> derive from input names, never raise
    assert render_clarify(pr, ["material"], locale="en-US") is not None


def test_po_filter_case():
    po = _cap("MM.PurchaseOrder.GetList")
    assert render_clarify(po, ["filter"]) == "请至少提供一个过滤条件（采购订单号、供应商、工厂或物料）。"


def test_sticky_clarify_rendered_from_declaration():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context

    context = ConversationContext(
        history=(),
        last_context=LastContext(
            capability_id="MM.PR.CreateDraft",
            decision_type="CLARIFY",
            parameters={"material": "DEMOA2", "quantity": "50"},
            missing_parameters=["plant", "unit", "delivery_date", "purchasing_group"],
        ),
    )
    result = resolve_with_context("工厂 1000 数量 50", context, load_intent_catalog())
    # Reconciliation #5: sticky PR clarification is now the declared text.
    assert result.clarification == "请提供: 单位, 交货日期, 采购组"
    assert result.missing_parameters == ["unit", "delivery_date", "purchasing_group"]


def test_sticky_inventory_clarify_matches_legacy_exactly():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context

    context = ConversationContext(
        history=(),
        last_context=LastContext(
            capability_id="MM.Inventory.GetAvailability",
            decision_type="CLARIFY",
            parameters={"plant": "1000"},
            missing_parameters=["material"],
        ),
    )
    result = resolve_with_context("继续查一下", context, load_intent_catalog())
    # Inventory single-turn and sticky texts coincide - stays strict.
    assert result.clarification == "请提供要查询的物料编号。"


class _FakeModel:
    def __init__(self, payload, *, delay=None, raise_exc=None):
        self.payload = payload
        self.delay = delay
        self.raise_exc = raise_exc
        self.calls = []

    def chat_json(self, messages, temperature=0.0, max_tokens=200):
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        if self.delay is not None:
            time.sleep(self.delay)
        if self.raise_exc is not None:
            raise self.raise_exc
        if isinstance(self.payload, list):
            next_payload = self.payload.pop(0)
            if isinstance(next_payload, BaseException):
                raise next_payload
            return next_payload
        return self.payload


def test_rephrase_accepts_in_scope_question():
    model = _FakeModel({"question": "想查哪个物料编号？"})

    result = clarify.rephrase_clarify(
        "请提供要查询的物料编号。",
        ["material"],
        {"material": "物料编号", "plant": "工厂"},
        {"material", "plant"},
        model,
    )

    assert result == "想查哪个物料编号？"


def test_rephrase_rejects_out_of_scope_field():
    model = _FakeModel({"question": "请告诉我要查的物料编号和工厂。"})

    result = clarify.rephrase_clarify(
        "请提供要查询的物料编号。",
        ["material"],
        {"material": "物料编号", "plant": "工厂"},
        {"material", "plant"},
        model,
    )

    assert result is None


def test_rephrase_rejects_malformed_json():
    model = _FakeModel({"notQuestion": "想查哪个物料编号？"})

    result = clarify.rephrase_clarify(
        "请提供要查询的物料编号。",
        ["material"],
        {"material": "物料编号"},
        {"material"},
        model,
    )

    assert result is None


def test_rephrase_rejects_nondict_payload_none():
    # adversarial: model returns None (non-object JSON)
    model = _FakeModel(None)

    result = clarify.rephrase_clarify(
        "请提供要查询的物料编号。",
        ["material"],
        {"material": "物料编号"},
        {"material"},
        model,
    )

    assert result is None


def test_rephrase_rejects_nondict_payload_list():
    # adversarial: model returns a non-dict JSON payload (a list)
    model = _FakeModel([[]])

    result = clarify.rephrase_clarify(
        "请提供要查询的物料编号。",
        ["material"],
        {"material": "物料编号"},
        {"material"},
        model,
    )

    assert result is None


def test_rephrase_rejects_timeout():
    model = _FakeModel({"question": "想查哪个物料编号？"}, delay=0.02)

    result = clarify.rephrase_clarify(
        "请提供要查询的物料编号。",
        ["material"],
        {"material": "物料编号"},
        {"material"},
        model,
        timeout_ms=1,
    )

    assert result is None


def test_pr_strategy_renders_one_prompt_per_group():
    pr = _cap("MM.PR.CreateDraft")
    # One prompt carries all missing fields of the (single) group.
    assert render_clarify(pr, ["quantity"]) == "请提供: 数量"
    assert render_clarify(pr, ["quantity", "unit"]) == "请提供: 数量, 单位"
    assert render_clarify(
        pr, ["material", "plant", "quantity", "unit", "delivery_date", "purchasing_group"]
    ) == "请提供: 物料编号, 工厂, 数量, 单位, 交货日期, 采购组"


def test_strategy_round_budget_respected_and_degrades_to_fallback():
    from sap_nexus_agent.extraction.clarify import render_clarify_round

    pr = _cap("MM.PR.CreateDraft")
    missing = ["plant", "unit", "delivery_date"]
    text, rounds = render_clarify_round(pr, missing, {})
    assert text == "请提供: 工厂, 单位, 交货日期"
    assert rounds == {"MM.PR.CreateDraft": 1}
    text, rounds = render_clarify_round(pr, missing, rounds)
    assert text == "请提供: 工厂, 单位, 交货日期"
    assert rounds == {"MM.PR.CreateDraft": 2}
    # Budget exhausted: degrade to the declared fallback template; no increment.
    text, rounds = render_clarify_round(pr, missing, rounds)
    assert text == "请提供: 工厂, 单位, 交货日期"
    assert rounds is None


def test_strategy_rounds_reset_on_capability_switch():
    from sap_nexus_agent.extraction.clarify import render_clarify_round

    pr = _cap("MM.PR.CreateDraft")
    text, rounds = render_clarify_round(pr, ["plant"], {"MM.Inventory.GetAvailability": 2})
    assert rounds == {"MM.PR.CreateDraft": 1}  # different capability: reset, then count


def test_strategy_groups_by_binding_source_kind(tmp_path):
    from sap_nexus_agent.extraction.clarify import render_clarify_with_kind
    from sap_nexus_agent.registry_loader import load_intent_catalog

    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "semantic-types.yaml").write_text(
        "version: 2\nsemanticTypes:\n  - id: MaterialNumber\n    description: synthetic\n"
        "    priority: 1\n    matchers:\n      - kind: regex\n        pattern: '[A-Z0-9]+'\n"
        "        justification: synthetic fixture\n",
        encoding="utf-8",
    )
    (registry / "capabilities.yaml").write_text(
        "capabilities:\n"
        "  - capabilityId: Test.Groups\n"
        "    status: active\n"
        "    intent:\n"
        "      intentName: test_groups\n"
        "      primaryKeywords: [测试]\n"
        "      fieldNames:\n"
        "        zh-CN:\n"
        "          vendor: 供应商\n"
        "          quantity: 数量\n"
        "      clarifyPrompt:\n"
        "        zh-CN:\n"
        "          strategy: groupByBindingKind\n"
        "          maxRounds: 2\n"
        "          cases:\n"
        "            - missing: [vendor]\n"
        "              text: '请提供供应商。'\n"
        "          fallback:\n"
        "            template: '请提供: {fields}'\n"
        "    inputs:\n"
        "      - name: vendor\n"
        "        semanticName: supplier\n"
        "        semanticType: sapnexus:Supplier\n"
        "        bindingKind: identifier\n"
        "        required: true\n"
        "        type: string\n"
        "        sapParameter: VENDOR\n"
        "        binding:\n"
        "          sources:\n"
        "            - kind: userUtterance\n"
        "              matchers:\n"
        "                - kind: regex\n"
        "                  pattern: '供应商\\s*([A-Z0-9]+)'\n"
        "      - name: quantity\n"
        "        semanticName: quantity\n"
        "        semanticType: sapnexus:Quantity\n"
        "        bindingKind: identifier\n"
        "        required: true\n"
        "        type: number\n"
        "        sapParameter: QTY\n"
        "        binding:\n"
        "          sources:\n"
        "            - kind: default\n"
        "              value: '1'\n",
        encoding="utf-8",
    )
    catalog = load_intent_catalog(str(tmp_path))
    cap = catalog.find("Test.Groups")
    assert cap is not None

    text, kind = render_clarify_with_kind(cap, ["vendor", "quantity"])
    assert kind == "strategy"
    # One prompt per group, groups in first-seen order of missing fields.
    assert text == "请提供: 供应商 请提供: 数量"

    # Explicit cases override strategy rendering (spec scenario).
    text, kind = render_clarify_with_kind(cap, ["vendor"])
    assert (text, kind) == ("请提供供应商。", "cases")


def test_hybrid_clarify_falls_back_to_template_on_model_failure():
    catalog = load_intent_catalog()
    model = _FakeModel([
        {"capabilityId": "MM.Inventory.GetAvailability", "parameters": {"plant": "1000"}},
        ValueError("rephrase failed"),
    ])

    result = parse_with_hybrid("查一下 1000 工厂库存", client=model, catalog=catalog)

    assert result.clarification == "请提供要查询的物料编号。"
    assert len(model.calls) == 2


def test_sticky_clarify_rounds_capped_via_read_state():
    from sap_nexus_agent.conversation_context import ConversationContext, LastContext
    from sap_nexus_agent.llm_intent import resolve_with_context
    from sap_nexus_agent.read_context import ConversationReadState

    def _sticky(rounds):
        context = ConversationContext(
            history=(),
            last_context=LastContext(
                capability_id="MM.PR.CreateDraft",
                decision_type="CLARIFY",
                parameters={"material": "DEMOA2", "quantity": "50"},
                missing_parameters=["plant", "unit", "delivery_date", "purchasing_group"],
            ),
            read_state=ConversationReadState(
                active_frame=None,
                pending_interaction=None,
                state_version=1,
                clarify_rounds=rounds or {},
            ),
        )
        return resolve_with_context("工厂 1000", context, load_intent_catalog())

    first = _sticky({})
    assert first.clarification == "请提供: 单位, 交货日期, 采购组"
    assert first.clarify_rounds == {"MM.PR.CreateDraft": 1}

    second = _sticky(first.clarify_rounds)
    assert second.clarify_rounds == {"MM.PR.CreateDraft": 2}

    third = _sticky(second.clarify_rounds)
    # Budget exhausted: fallback template, rounds not incremented.
    assert third.clarification == "请提供: 单位, 交货日期, 采购组"
    assert third.clarify_rounds is None
