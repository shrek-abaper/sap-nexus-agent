from __future__ import annotations

from time import monotonic
from typing import Final, Mapping, Protocol

from sap_nexus_agent.registry_loader import CapabilityDescriptor

ACTIVE_LOCALE: Final = "zh-CN"
_STRATEGY_TEMPLATE: Final = "请提供: {fields}"
_STRATEGY_MAX_ROUNDS_DEFAULT: Final = 2


class ClarifyRephraseModel(Protocol):
    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> dict[str, object]:
        ...


def _field_names(cap: CapabilityDescriptor, locale: str) -> dict[str, str]:
    intent_config = cap.intent_config
    if intent_config is None:
        return {}
    for loc, names in intent_config.field_names:
        if loc == locale:
            return dict(names)
    return {}


def _prompt_for_locale(cap: CapabilityDescriptor, locale: str):
    intent_config = cap.intent_config
    if intent_config is None:
        return None
    for loc, cfg in intent_config.clarify_prompt:
        if loc == locale:
            return cfg
    return None


def render_clarify(
    cap: CapabilityDescriptor,
    missing: list[str],
    locale: str = ACTIVE_LOCALE,
) -> str | None:
    text, _kind = render_clarify_with_kind(cap, missing, locale=locale)
    return text


def render_clarify_with_kind(
    cap: CapabilityDescriptor,
    missing: list[str],
    locale: str = ACTIVE_LOCALE,
    clarify_rounds: Mapping[str, int] | None = None,
) -> tuple[str | None, str]:
    """Render a clarification; return (text, kind) with kind in
    {"none", "cases", "strategy", "fallback"}.

    Order (Design §3.5): exact cases override -> strategy rendering under the
    round budget -> declared fallback template.
    """
    if not missing or cap.intent_config is None:
        return None, "none"

    prompt = _prompt_for_locale(cap, locale)
    if prompt is None:
        if locale != ACTIVE_LOCALE:
            names = _field_names(cap, ACTIVE_LOCALE)
            fields = ", ".join(names.get(name, name) for name in missing)
            return f"请提供: {fields}", "fallback"
        return None, "none"

    missing_set = frozenset(missing)
    for case in prompt.cases:
        if case.missing == missing_set:
            return case.text, "cases"

    if prompt.strategy is not None:
        rounds = clarify_rounds or {}
        max_rounds = (
            prompt.max_rounds
            if prompt.max_rounds is not None
            else _STRATEGY_MAX_ROUNDS_DEFAULT
        )
        if rounds.get(cap.capability_id, 0) < max_rounds:
            template = prompt.fallback_template or _STRATEGY_TEMPLATE
            parts = []
            for _group, fields in _missing_by_group(cap, missing).items():
                names = _field_names(cap, locale)
                parts.append(
                    template.replace("{fields}", ", ".join(names.get(name, name) for name in fields))
                )
            return " ".join(parts), "strategy"

    if prompt.fallback_template is None:
        return None, "none"
    names = _field_names(cap, locale)
    fields = ", ".join(names.get(name, name) for name in missing)
    return prompt.fallback_template.replace("{fields}", fields), "fallback"


def render_clarify_round(
    cap: CapabilityDescriptor,
    missing: list[str],
    clarify_rounds: Mapping[str, int] | None,
    locale: str = ACTIVE_LOCALE,
) -> tuple[str | None, Mapping[str, int] | None]:
    """Render against the round budget.

    Returns (text, next_rounds): next_rounds carries the incremented counter
    for the capability when a strategy prompt was rendered, else None
    (fallback rendering does not increment - the budget is already exhausted).
    """
    text, kind = render_clarify_with_kind(
        cap, missing, locale=locale, clarify_rounds=clarify_rounds
    )
    if kind != "strategy":
        return text, None
    rounds = dict(clarify_rounds or {})
    if cap.capability_id not in rounds:
        # Coordinator ruling (2026-08-20): reset the budget when the turn's
        # capability is not yet tracked (pins test_strategy_rounds_reset_on_capability_switch).
        # The sticky callers (2.4) reset before calling; this internal reset
        # is redundant-but-harmless there and makes the function total.
        rounds = {}
    rounds[cap.capability_id] = rounds.get(cap.capability_id, 0) + 1
    return text, rounds


def _missing_by_group(cap: CapabilityDescriptor, missing: list[str]) -> dict[str, list[str]]:
    """Group missing fields by their input's first binding source kind."""
    groups: dict[str, list[str]] = {}
    for name in missing:
        group = "userUtterance"
        inp = next((i for i in cap.inputs if i.name == name), None)
        # Coordinator ruling (2026-08-20): InputDescriptor.binding lands in task 3.2;
        # until then every input falls into the default userUtterance group
        # (plan Interfaces: "until then the loader normalizes extraction →
        # userUtterance group"). getattr keeps 2.3 tests green pre-3.2.
        binding = getattr(inp, "binding", None)
        if binding is not None and binding.sources:
            group = binding.sources[0].kind
        groups.setdefault(group, []).append(name)
    return groups


def rephrase_clarify(
    template_text: str,
    missing: list[str],
    field_names: dict[str, str],
    all_declared_fields: set[str],
    model: ClarifyRephraseModel,
    timeout_ms: int = 3000,
) -> str | None:
    """Return a grounded cosmetic rephrase, or None when safety checks fail."""
    if not template_text or not missing:
        return None

    started = monotonic()
    try:
        payload = model.chat_json(
            _rephrase_messages(template_text, missing, field_names),
            temperature=0.0,
            max_tokens=200,
        )
    except TimeoutError:
        return None
    except Exception:  # noqa: BLE001 - optional cosmetic LLM boundary must fail closed.
        return None

    elapsed_ms = (monotonic() - started) * 1000
    if elapsed_ms > timeout_ms:
        return None

    # payload must be a JSON object (dict). If the model returned a non-dict
    # (list, None, string, int, etc.) treat it as malformed and fail closed.
    if not isinstance(payload, dict):
        return None
    question = payload.get("question")
    if not isinstance(question, str):
        return None
    question = question.strip()
    if not question:
        return None
    if _mentions_forbidden_field(question, missing, field_names, all_declared_fields):
        return None
    if not _mentions_missing_field(question, missing, field_names):
        return None
    return question


def _rephrase_messages(
    template_text: str,
    missing: list[str],
    field_names: dict[str, str],
) -> list[dict[str, str]]:
    missing_fields = [f"{name}: {field_names.get(name, name)}" for name in missing]
    return [
        {
            "role": "system",
            "content": (
                "Rephrase the clarification question into natural Chinese. "
                "Ask only about the listed missing fields. Do not add new fields, facts, "
                "examples, values, or SAP details. Return strict JSON matching this schema: "
                '{"question": "string"}.'
            ),
        },
        {
            "role": "user",
            "content": (
                f"Template question: {template_text}\n"
                f"Missing fields: {missing_fields}\n"
                "Return only the JSON object."
            ),
        },
    ]


def _mentions_forbidden_field(
    question: str,
    missing: list[str],
    field_names: dict[str, str],
    all_declared_fields: set[str],
) -> bool:
    missing_set = set(missing)
    forbidden_fields = all_declared_fields - missing_set
    return any(
        _contains_term(question, term)
        for field in forbidden_fields
        for term in (field, field_names.get(field, ""))
        if term
    )


def _mentions_missing_field(
    question: str,
    missing: list[str],
    field_names: dict[str, str],
) -> bool:
    return any(
        _contains_term(question, term)
        for field in missing
        for term in (field, field_names.get(field, ""))
        if term
    )


def _contains_term(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()
