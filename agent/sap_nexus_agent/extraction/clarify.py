from __future__ import annotations

from time import monotonic
from typing import Final, Protocol

from sap_nexus_agent.registry_loader import CapabilityDescriptor

ACTIVE_LOCALE: Final = "zh-CN"


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


def render_clarify(
    cap: CapabilityDescriptor,
    missing: list[str],
    locale: str = ACTIVE_LOCALE,
) -> str | None:
    intent_config = cap.intent_config
    if not missing or intent_config is None:
        return None

    prompt = None
    for loc, cfg in intent_config.clarify_prompt:
        if loc == locale:
            prompt = cfg
            break

    if prompt is None:
        if locale != ACTIVE_LOCALE:
            names = _field_names(cap, ACTIVE_LOCALE)
            fields = ", ".join(names.get(name, name) for name in missing)
            return f"请提供: {fields}"
        return None

    missing_set = frozenset(missing)
    for case in prompt.cases:
        if case.missing == missing_set:
            return case.text

    if prompt.fallback_template is None:
        return None

    names = _field_names(cap, locale)
    fields = ", ".join(names.get(name, name) for name in missing)
    return prompt.fallback_template.replace("{fields}", fields)


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
