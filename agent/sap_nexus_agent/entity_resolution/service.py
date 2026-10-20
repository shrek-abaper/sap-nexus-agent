"""Server-side entity resolution orchestration (spec: entity-resolution-orchestration).

Runs in the IO layer: searches through the governed MD.*.Search READ
capability (never direct DB access from the agent), then decides per the
ontology confirmation policy:

- exact code + visible + active -> bind with evidence (ResolvedEntityRef)
- anything else -> EntityChoiceSet for user confirmation (conservative v1)

Natural-language selection is deterministic: ordinals bind to the ORIGINAL
display order, attribute phrases only filter the current candidate set's
real attributes, "都不是" clears, and anything else becomes a new mention.
The model never turns "我选了第二个" into a self-certified code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Mapping, Protocol

from sap_nexus_agent.entity_resolution.models import (
    EntityCandidateView,
    EntityChoiceSet,
    ResolvedEntityRef,
)
from sap_nexus_agent.entity_resolution.rules import EntityResolutionRule

# --- outcome models -----------------------------------------------------------


@dataclass(frozen=True)
class BindOutcome:
    ref: ResolvedEntityRef


@dataclass(frozen=True)
class ChooseOutcome:
    choice_set: EntityChoiceSet


@dataclass(frozen=True)
class ClarifyOutcome:
    reason: str  # no-match | provider-unavailable | permission-denied | coverage-incomplete
    message: str


ResolutionOutcome = BindOutcome | ChooseOutcome | ClarifyOutcome


class SearchGateway(Protocol):
    """Minimal governed search channel (matches GatewayClientProtocol)."""

    def execute(self, capability_id: str, parameters: Mapping[str, object]): ...


# --- selection parsing ---------------------------------------------------------

_ORDINAL_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                   "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_REFUSE = ("都不是", "都不对", "没有我要的", "都不是我要的")
_FILLER = ("那个公司", "的那家", "的那个", "那个", "那家", "这家", "的", "个")


@dataclass(frozen=True)
class SelectionByIndex:
    index: int


@dataclass(frozen=True)
class SelectionRefused:
    pass


@dataclass(frozen=True)
class SelectionRefined:
    """Attribute phrase narrowed the set; remaining candidate indexes."""

    remaining: tuple[int, ...]


@dataclass(frozen=True)
class SelectionNewMention:
    text: str


SelectionResult = SelectionByIndex | SelectionRefused | SelectionRefined | SelectionNewMention


def parse_selection(text: str, choice_set: EntityChoiceSet) -> SelectionResult:
    """Deterministically interpret a user reply against the CURRENT set."""
    stripped = text.strip()
    if any(marker in stripped for marker in _REFUSE):
        return SelectionRefused()

    ordinal = re.fullmatch(r"第\s*(\d{1,2}|[一二两三四五六七八九十])\s*(?:个|项|家|条)?", stripped)
    if ordinal:
        token = ordinal.group(1)
        index = int(token) if token.isdigit() else _ORDINAL_DIGITS[token]
        return SelectionByIndex(index)
    if re.fullmatch(r"\d{1,2}", stripped):
        return SelectionByIndex(int(stripped))

    # Attribute phrase: strip fillers, match against real candidate attributes.
    phrase = stripped
    for filler in _FILLER:
        phrase = phrase.replace(filler, "")
    phrase = phrase.strip()
    if not phrase:
        return SelectionNewMention(stripped)
    remaining: list[int] = []
    for candidate in choice_set.candidates:
        haystacks = [candidate.display_name, candidate.canonical_code]
        haystacks.extend(value for _key, value in candidate.distinguishing)
        haystacks.extend(value for _field, value in candidate.org_scopes)
        if any(phrase.lower() in hay.lower() for hay in haystacks if hay):
            remaining.append(candidate.index)
    if len(remaining) == 1:
        return SelectionByIndex(remaining[0])
    if len(remaining) > 1:
        return SelectionRefined(tuple(remaining))
    return SelectionNewMention(stripped)


# --- service -------------------------------------------------------------------


class EntityResolutionService:
    def __init__(self, gateway: SearchGateway, *, provider: str = "PG_MASTERDATA_READ"):
        self._gateway = gateway
        self._provider = provider

    def resolve(
        self,
        *,
        rule: EntityResolutionRule,
        target_capability_id: str,
        target_slot: str,
        mention_text: str,
        entity_key: str | None,
        org_filters: Mapping[str, str],
        principal_id: str,
        registry_snapshot_id: str,
        frame_id: str,
        turn_id: str,
        server_time: datetime | None = None,
    ) -> ResolutionOutcome:
        """Search through the governed capability and decide per policy."""
        parameters: dict[str, object] = {}
        if entity_key:
            parameters["entityKey"] = entity_key
        elif mention_text.strip():
            parameters["query"] = mention_text.strip()
        else:
            return ClarifyOutcome("no-match", "没有可用于检索的描述或编码。")
        for field, value in org_filters.items():
            if value:
                parameters[field] = value

        try:
            execution = self._gateway.execute(rule.search_capability_id, parameters)
        except Exception:
            return ClarifyOutcome("provider-unavailable", "主数据检索服务暂时不可用，请稍后重试。")
        if not getattr(execution, "success", False):
            error_type = str(getattr(execution, "error_type", "") or "")
            if "PERMISSION" in error_type:
                return ClarifyOutcome("permission-denied", "当前身份无权检索该主数据范围。")
            return ClarifyOutcome("provider-unavailable", "主数据检索服务暂时不可用，请稍后重试。")

        data = getattr(execution, "data", {}) or {}
        raw_candidates = data.get("candidates") or []
        snapshot_id = str(data.get("snapshotId") or "unknown")
        source_extracted_at = str(data.get("sourceExtractedAt") or "") or None
        now = server_time or datetime.now(UTC)

        views = tuple(
            EntityCandidateView(
                index=position,
                canonical_code=str(item.get("canonicalCode") or ""),
                display_name=str(item.get("displayName") or ""),
                distinguishing=tuple(sorted(
                    (str(k), str(v)) for k, v in (item.get("distinguishing") or {}).items()
                )),
                match_kind=str(item.get("matchKind") or ""),
                status=str(item.get("status") or "active"),
                org_scopes=tuple(
                    (str(scope.get("field")), str(scope.get("value")))
                    for scope in (item.get("orgScopes") or [])
                ),
            )
            for position, item in enumerate(raw_candidates, start=1)
            if item.get("canonicalCode")
        )

        # Exact-code path: bind only when the code is visible AND active.
        if entity_key:
            active = [v for v in views if v.status == "active"]
            if len(active) == 1 and rule.confirm_exact_code is False:
                return BindOutcome(ResolvedEntityRef(
                    canonical_code=active[0].canonical_code,
                    object_type=rule.object_type_id,
                    target_slot=target_slot,
                    resolution="exact-code",
                    snapshot_id=snapshot_id,
                    candidate_set_id=None,
                    frame_id=frame_id,
                ))
            if not active:
                return ClarifyOutcome(
                    "no-match",
                    f"编码 {entity_key} 在当前可见范围内不存在或已失效，请核对或改用描述检索。",
                )
            # Multiple hits for one code should not happen; treat as choice.

        if not views:
            return ClarifyOutcome(
                "no-match",
                "没有找到匹配的对象，请补充描述、型号或城市等信息（不需要记得编码）。",
            )

        choice_set = EntityChoiceSet(
            candidate_set_id=EntityChoiceSet.issue_id(
                object_type=rule.object_type_id,
                target_slot=rule.identifier_field,
                mention=entity_key or mention_text.strip(),
                codes=tuple(v.canonical_code for v in views),
                snapshot_id=snapshot_id,
            ),
            object_type=rule.object_type_id,
            target_capability_id=target_capability_id,
            target_slot=target_slot,
            mention=entity_key or mention_text.strip(),
            candidates=views,
            snapshot_id=snapshot_id,
            provider=self._provider,
            created_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
            principal_id=principal_id,
            registry_snapshot_id=registry_snapshot_id,
            source_extracted_at=source_extracted_at,
        )
        return ChooseOutcome(choice_set)
