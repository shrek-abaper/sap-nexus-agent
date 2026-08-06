"""Pure, advisory candidate extraction for governed READ context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from sap_nexus_agent.discard import prohibited_field_reason
from sap_nexus_agent.intent_envelope import IntentEnvelope
from sap_nexus_agent.registry_loader import CapabilityDescriptor, InputDescriptor

_SEMANTIC_LABELS = {
    "purchaseordernumber": ("采购订单", "po"),
    "supplier": ("供应商",),
    "unitofmeasure": ("单位",),
}


@dataclass(frozen=True)
class ContextCandidate:
    slot: str
    value: str
    source: str
    source_span: tuple[int, int] | None = None


@dataclass(frozen=True)
class SlotCandidates:
    slot: str
    candidates: tuple[ContextCandidate, ...]

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(candidate.value for candidate in self.candidates)

    @property
    def deterministic_values(self) -> tuple[str, ...]:
        return tuple(
            candidate.value
            for candidate in self.candidates
            if candidate.source
            in {"DETERMINISTIC_LABEL", "EXPLICIT_CORRECTION", "CONFIRMATION"}
        )

    @property
    def model_values(self) -> tuple[str, ...]:
        return tuple(
            candidate.value
            for candidate in self.candidates
            if candidate.source == "MODEL_CANDIDATE"
        )

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(candidate.source for candidate in self.candidates)


@dataclass(frozen=True)
class ContextCandidateSet:
    slots: Mapping[str, SlotCandidates]
    clear_slots: tuple[str, ...]
    discard_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))

    def for_slot(self, name: str) -> SlotCandidates:
        return self.slots.get(name, SlotCandidates(name, ()))


def extract_context_candidates(
    utterance: str,
    descriptor: CapabilityDescriptor,
    envelope: IntentEnvelope | None,
) -> ContextCandidateSet:
    """Extract evidence without resolving slots or mutating conversation state."""
    by_slot: dict[str, list[ContextCandidate]] = {input_.name: [] for input_ in descriptor.inputs}
    discards: list[str] = list(envelope.discard_reasons) if envelope is not None else []

    for input_ in descriptor.inputs:
        for value, span, source in _deterministic_values(utterance, input_):
            _append_if_valid(by_slot, discards, input_, value, source, span)

    if envelope is not None:
        for goal in envelope.goals:
            if goal.capability_hint != descriptor.capability_id:
                continue
            for name, value in goal.parameters.items():
                prohibited_reason = prohibited_field_reason(name)
                if prohibited_reason is not None:
                    _append_unique(discards, prohibited_reason)
                    continue
                input_ = _find_input(descriptor.inputs, name)
                if input_ is None:
                    _append_unique(discards, f"unknown_input:{name}")
                    continue
                _append_if_valid(by_slot, discards, input_, value, "MODEL_CANDIDATE", None)

    slots = {
        name: SlotCandidates(name, tuple(candidates)) for name, candidates in by_slot.items()
    }
    return ContextCandidateSet(
        slots=slots,
        clear_slots=_clear_slots(utterance, descriptor.inputs),
        discard_reasons=tuple(discards),
    )


def _find_input(inputs: tuple[InputDescriptor, ...], name: str) -> InputDescriptor | None:
    for input_ in inputs:
        if input_.name == name:
            return input_
    return None


def _deterministic_values(
    utterance: str, input_: InputDescriptor
) -> tuple[tuple[str, tuple[int, int], str], ...]:
    kind = _semantic_kind(input_)
    if kind == "plant":
        patterns = (
            (r"(?:工厂|plant)\s*(?:改成|是指)\s*([A-Za-z0-9]+)", "EXPLICIT_CORRECTION"),
            (r"(?:对\s*，?\s*就是)\s*(?:工厂|plant)\s*([A-Za-z0-9]+)", "CONFIRMATION"),
            (r"([A-Za-z0-9]+)\s*(?:是|为)\s*(?:工厂|plant)", "EXPLICIT_CORRECTION"),
            (r"(?:工厂|plant)\s*(?:是|为|:|：)?\s*([A-Za-z0-9]+)", "DETERMINISTIC_LABEL"),
            (r"([A-Za-z0-9]+)\s*(?:工厂|plant)", "DETERMINISTIC_LABEL"),
        )
    elif kind == "material":
        patterns = (
            (
                r"(?:物料|material)\s*(?:改成|是指)\s*(?:上面的)?\s*([A-Za-z0-9-]+)",
                "EXPLICIT_CORRECTION",
            ),
            (r"(?:对\s*，?\s*就是)\s*(?:物料|material)\s*([A-Za-z0-9-]+)", "CONFIRMATION"),
            (r"([A-Za-z0-9-]+)\s*(?:是|为)\s*(?:物料|material)", "EXPLICIT_CORRECTION"),
            (r"(?:物料|material)\s*(?:是|为|:|：)?\s*([A-Za-z0-9-]+)", "DETERMINISTIC_LABEL"),
        )
    else:
        patterns = _generic_label_patterns(input_)

    values: list[tuple[str, tuple[int, int], str]] = []
    for pattern, source in patterns:
        for match in re.finditer(pattern, utterance, flags=re.IGNORECASE):
            values.append((match.group(1), match.span(1), source))
    return tuple(values)


def _generic_label_patterns(input_: InputDescriptor) -> tuple[tuple[str, str], ...]:
    labels = _input_labels(input_)
    if not labels:
        return ()
    label_group = "|".join(re.escape(label) for label in labels)
    return (
        (rf"(?:{label_group})\s*(?:改成|是指)\s*([A-Za-z0-9_-]+)", "EXPLICIT_CORRECTION"),
        (rf"(?:对\s*，?\s*就是)\s*(?:{label_group})\s*([A-Za-z0-9_-]+)", "CONFIRMATION"),
        (rf"([A-Za-z0-9_-]+)\s*(?:是|为)\s*(?:{label_group})", "EXPLICIT_CORRECTION"),
        (rf"(?:{label_group})\s*(?:是|为|:|：)?\s*([A-Za-z0-9_-]+)", "DETERMINISTIC_LABEL"),
        (rf"([A-Za-z0-9_-]+)\s*(?:{label_group})", "DETERMINISTIC_LABEL"),
    )


def _input_labels(input_: InputDescriptor) -> tuple[str, ...]:
    labels = [input_.name, _humanize_identifier(input_.semantic_name)]
    semantic_type = input_.semantic_type.rsplit(":", maxsplit=1)[-1].lower()
    labels.extend(_SEMANTIC_LABELS.get(semantic_type, ()))
    return tuple(label for label in labels if label)


def _humanize_identifier(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value).replace("_", " ")


def _clear_slots(utterance: str, inputs: tuple[InputDescriptor, ...]) -> tuple[str, ...]:
    clearable = []
    for input_ in inputs:
        if _semantic_kind(input_) == "material" and re.search(r"换个\s*(?:物料|material)", utterance, re.IGNORECASE):
            clearable.append(input_.name)
    return tuple(clearable)


def _semantic_kind(input_: InputDescriptor) -> str | None:
    semantic_type = input_.semantic_type.lower()
    if semantic_type.endswith("materialnumber"):
        return "material"
    if semantic_type.endswith("plant"):
        return "plant"
    return None


def _append_if_valid(
    by_slot: dict[str, list[ContextCandidate]],
    discards: list[str],
    input_: InputDescriptor,
    value: object,
    source: str,
    source_span: tuple[int, int] | None,
) -> None:
    if not isinstance(value, str) or not value.strip() or not is_semantically_valid(input_, value):
        _append_unique(discards, f"invalid_semantic_value:{input_.name}:{value}")
        return
    candidate = ContextCandidate(input_.name, value.strip(), source, source_span)
    if candidate not in by_slot[input_.name]:
        by_slot[input_.name].append(candidate)


def is_semantically_valid(input_: InputDescriptor, value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if input_.min_length is not None and len(normalized) < input_.min_length:
        return False
    if input_.max_length is not None and len(normalized) > input_.max_length:
        return False
    if input_.pattern is not None and re.fullmatch(input_.pattern, normalized) is None:
        return False
    if _semantic_kind(input_) == "plant":
        return re.fullmatch(r"[A-Z0-9]{4}", normalized) is not None
    return True


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
