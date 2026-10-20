"""Orchestration glue between the governed READ turn and entity resolution.

Pure coordination helpers: the orchestrator calls these from the IO layer.
All database access goes through the governed MD.*.Search capability; the
reducer stays IO-free and only ever sees validated CONFIRMATION candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Mapping

from sap_nexus_agent.entity_resolution.models import (
    EntityCandidateView,
    EntityChoiceSet,
)
from sap_nexus_agent.entity_resolution.rules import (
    EntityResolutionRule,
    load_resolution_rules,
)
from sap_nexus_agent.entity_resolution.service import (
    BindOutcome,
    ChooseOutcome,
    ClarifyOutcome,
    EntityResolutionService,
    ResolutionOutcome,
    SelectionByIndex,
    SelectionNewMention,
    SelectionRefined,
    SelectionRefused,
    parse_selection,
)

# Longest phrases first: replacement is sequential substring removal.
_STOPWORDS = (
    "查一下", "帮我查", "未清应收", "未清应付", "查询", "告诉我",
    "销售订单", "采购订单", "公司代码", "有限公司", "未清项", "有哪些", "未清", "应收", "应付", "账款",
    "库存", "还有多少", "多少", "还有", "什么",
    "在", "的", "是", "有", "工厂", "公司", "呢", "吗", "？", "?",
)
_EXPIRY_MINUTES = 15


def extract_mention(utterance: str, resolved_values: tuple[str, ...]) -> str:
    """Best-effort deterministic mention: utterance minus bound slot values
    and capability stopwords. Never treated as an identifier."""
    # Server-appended slot hints ("[已知条件] ..." from buildToolQuery) only
    # repeat already-bound values; they must not pollute the mention.
    mention = utterance.split("[已知条件", 1)[0]
    for value in resolved_values:
        if value:
            mention = mention.replace(value, " ")
    for stopword in _STOPWORDS:
        mention = mention.replace(stopword, " ")
    # Clause punctuation carries no retrieval value (e.g. "苏州豪骏，").
    mention = re.sub(r"[，。、；：,.;:!?()（）\[\]【】]", " ", mention)
    return re.sub(r"\s+", " ", mention).strip()


@dataclass(frozen=True)
class SlotResolutionTarget:
    rule: EntityResolutionRule
    slot: str
    org_filters: tuple[tuple[str, str], ...]


def find_resolution_target(
    *,
    descriptor,
    frame_slots: Mapping[str, object],
    missing_required: tuple[str, ...],
    rules: tuple[EntityResolutionRule, ...] | None = None,
) -> SlotResolutionTarget | None:
    """First missing required slot with an entity-resolution rule."""
    if not missing_required:
        return None
    if rules is None:
        rules = load_resolution_rules()
    by_semantic = {rule.identifier_semantic_type: rule for rule in rules}
    inputs = {input_.name: input_ for input_ in descriptor.inputs}
    for slot in missing_required:
        input_ = inputs.get(slot)
        if input_ is None:
            continue
        rule = by_semantic.get(getattr(input_, "semantic_type", ""))
        if rule is None:
            continue
        org_filters = tuple(
            (field, getattr(frame_slots.get(field), "value", "") or "")
            for field, _semantic in rule.organizational_filters
            if getattr(frame_slots.get(field), "value", None)
        )
        return SlotResolutionTarget(rule=rule, slot=slot, org_filters=org_filters)
    return None


@dataclass(frozen=True)
class EntityTurnDecision:
    """What an ENTITY_CHOICE pending turn resolved to."""

    kind: str  # confirm | refuse | clarify | new-choice | stale
    slot: str = ""
    code: str = ""
    capability_id: str = ""
    message: str = ""
    choice_set: EntityChoiceSet | None = None


def resolve_entity_choice_turn(
    *,
    text: str,
    choice_set: EntityChoiceSet,
    gateway,
    principal_id: str,
    registry_snapshot_id: str,
    frame_id: str,
    turn_id: str,
    rules: tuple[EntityResolutionRule, ...] | None = None,
) -> EntityTurnDecision:
    """Interpret a reply against the server-side candidate set.

    The reply can only reference the current set: ordinals bind to the
    original display order, attribute phrases filter real attributes, and a
    new mention starts a fresh search (the old handle dies with it).
    """
    if choice_set.principal_id != principal_id:
        # Cross-principal handles never resolve (spec §11 case 18).
        return EntityTurnDecision(kind="stale", message="候选集不属于当前身份，已失效，请重新检索。")
    if rules is None:
        rules = load_resolution_rules()
    rule = next((r for r in rules if r.object_type_id == choice_set.object_type), None)
    if rule is None:
        return EntityTurnDecision(kind="stale", message="实体解析规则已变更，请重新描述目标。")
    if choice_set.registry_snapshot_id != registry_snapshot_id:
        # Conservative v1: configuration drift invalidates the pending set.
        return EntityTurnDecision(kind="stale", message="检索配置已更新，请重新描述目标对象。")

    selection = parse_selection(text, choice_set)
    if isinstance(selection, SelectionRefused):
        return EntityTurnDecision(
            kind="refuse", message="已清除当前候选，请重新描述要找的对象。",
        )
    if isinstance(selection, SelectionNewMention):
        new_outcome = _search(
            rule=rule, gateway=gateway, target_capability_id=choice_set.target_capability_id,
            target_slot=choice_set.target_slot, mention=selection.text,
            entity_key=None, org_filters=(), principal_id=principal_id,
            registry_snapshot_id=registry_snapshot_id, frame_id=frame_id, turn_id=turn_id,
        )
        if isinstance(new_outcome, ChooseOutcome):
            return EntityTurnDecision(kind="new-choice", choice_set=new_outcome.choice_set)
        if isinstance(new_outcome, ClarifyOutcome):
            return EntityTurnDecision(kind="clarify", message=new_outcome.message)
        return EntityTurnDecision(kind="stale", message="检索异常，请重新描述目标。")
    if isinstance(selection, SelectionRefined):
        remaining = ", ".join(
            f"{i}（{choice_set.candidates[i - 1].display_name}）" for i in selection.remaining
        )
        return EntityTurnDecision(
            kind="clarify",
            message=f"仍有多个匹配：{remaining}。请补充一个区分条件（如城市、规格），或回复序号。",
        )

    index = selection.index
    if index < 1 or index > len(choice_set.candidates):
        return EntityTurnDecision(
            kind="clarify",
            message=f"序号 {index} 不在候选范围内（1–{len(choice_set.candidates)}），请重新选择。",
        )
    candidate = choice_set.candidates[index - 1]

    # Confirm-time revalidation (spec §8.3): the entity must still exist, be
    # active, and be visible in the CURRENT snapshot before binding.
    revalidation = _search(
        rule=rule, gateway=gateway, target_capability_id=choice_set.target_capability_id,
        target_slot=choice_set.target_slot, mention=candidate.canonical_code,
        entity_key=candidate.canonical_code, org_filters=(), principal_id=principal_id,
        registry_snapshot_id=registry_snapshot_id, frame_id=frame_id, turn_id=turn_id,
    )
    if not isinstance(revalidation, BindOutcome):
        return EntityTurnDecision(
            kind="stale",
            message=f"所选对象（{candidate.display_name}）当前不可用或数据已变更，请重新解析。",
        )
    return EntityTurnDecision(
        kind="confirm",
        slot=choice_set.target_slot,
        code=candidate.canonical_code,
        capability_id=choice_set.target_capability_id,
    )


def attempt_slot_resolution(
    *,
    text: str,
    descriptor,
    frame_slots: Mapping[str, object],
    missing_required: tuple[str, ...],
    gateway,
    principal_id: str,
    registry_snapshot_id: str,
    frame_id: str,
    turn_id: str,
    resolved_values: tuple[str, ...],
    rules: tuple[EntityResolutionRule, ...] | None = None,
) -> ResolutionOutcome | None:
    """Try to resolve a missing required slot from the user's description."""
    target = find_resolution_target(
        descriptor=descriptor, frame_slots=frame_slots,
        missing_required=missing_required, rules=rules,
    )
    if target is None:
        return None
    mention = extract_mention(text, resolved_values)
    if not mention:
        return None
    return _search(
        rule=target.rule, gateway=gateway,
        target_capability_id=descriptor.capability_id, target_slot=target.slot,
        mention=mention, entity_key=None, org_filters=target.org_filters,
        principal_id=principal_id, registry_snapshot_id=registry_snapshot_id,
        frame_id=frame_id, turn_id=turn_id,
    )


def _search(
    *,
    rule: EntityResolutionRule,
    gateway,
    target_capability_id: str,
    target_slot: str,
    mention: str,
    entity_key: str | None,
    org_filters: tuple[tuple[str, str], ...],
    principal_id: str,
    registry_snapshot_id: str,
    frame_id: str,
    turn_id: str,
) -> ResolutionOutcome:
    service = EntityResolutionService(gateway)
    return service.resolve(
        rule=rule,
        target_capability_id=target_capability_id,
        target_slot=target_slot,
        mention_text=mention,
        entity_key=entity_key,
        org_filters=dict(org_filters),
        principal_id=principal_id,
        registry_snapshot_id=registry_snapshot_id,
        frame_id=frame_id,
        turn_id=turn_id,
    )


def render_choice_question(choice_set: EntityChoiceSet) -> str:
    """Deterministic candidate question; no model-generated attributes."""
    lines = [f"找到 {len(choice_set.candidates)} 个可能的匹配，请回复序号选择，或补充区分条件："]
    for candidate in choice_set.candidates:
        details = "，".join(
            f"{key}={value}" for key, value in candidate.distinguishing if value
        )
        orgs = "，".join(f"{field}={value}" for field, value in candidate.org_scopes)
        suffix = "；".join(part for part in (details, orgs) if part)
        lines.append(
            f"{candidate.index}. {candidate.display_name}（{candidate.canonical_code}）"
            + (f" — {suffix}" if suffix else "")
        )
    freshness = choice_set.source_extracted_at or "unknown"
    lines.append(f"数据来源：主数据检索投影（快照提取时间：{freshness}）。也可以回复“都不是”重新描述。")
    return "\n".join(lines)
