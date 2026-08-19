from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class InputDescriptor:
    name: str
    semantic_name: str
    semantic_type: str = ""
    binding_kind: str | None = None
    required: bool = False
    type: str = "string"
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    extraction: ExtractionConfig | None = None


@dataclass(frozen=True)
class MatcherConfig:
    """Single matcher declaration inside an extraction / semantic type."""

    kind: str
    pattern: str | None = None
    value: str | None = None
    ref: str | None = None
    ignore_case: bool = False
    scan: str = "first"


@dataclass(frozen=True)
class ConditionConfig:
    field: str
    equals: str


@dataclass(frozen=True)
class ValueFilters:
    min_length: int | None = None
    not_in: tuple[str, ...] = ()
    prefix_blacklist: tuple[str, ...] = ()
    to_upper_compare: bool = False
    to_upper_output: bool = False


@dataclass(frozen=True)
class ExtractionConfig:
    """Per-input extraction declaration (declarative intent extraction)."""

    matchers: tuple[MatcherConfig, ...]
    priority: int = 0
    excludes: tuple[str, ...] = ()
    resolver: str = "text"
    when: ConditionConfig | None = None
    required_when: ConditionConfig | None = None
    reask_suspect: bool = False


@dataclass(frozen=True)
class ClarifyCase:
    missing: frozenset[str]
    text: str


@dataclass(frozen=True)
class ClarifyPromptConfig:
    cases: tuple[ClarifyCase, ...] = ()
    fallback_template: str | None = None


@dataclass(frozen=True)
class RequireAnyConfig:
    inputs: tuple[str, ...]
    missing_name: str


@dataclass(frozen=True)
class IntentConfig:
    """Intent declaration block on a capability (declarative intent extraction)."""

    intent_name: str
    primary_keywords: tuple[str, ...]
    weak_keywords: tuple[str, ...] = ()
    trigger_keywords: tuple[str, ...] | None = None
    field_names: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    clarify_prompt: tuple[tuple[str, ClarifyPromptConfig], ...] = ()
    require_any: RequireAnyConfig | None = None


@dataclass(frozen=True)
class SemanticTypeEntry:
    entry_id: str
    priority: int
    matchers: tuple[MatcherConfig, ...]
    filters: ValueFilters


@dataclass(frozen=True)
class SemanticTypeCatalog:
    entries: tuple[SemanticTypeEntry, ...] = ()

    def find(self, entry_id: str) -> SemanticTypeEntry | None:
        for entry in self.entries:
            if entry.entry_id == entry_id:
                return entry
        return None


@dataclass(frozen=True)
class NarrativeConfig:
    """Narrative declaration for a capability (metadata-driven narration)."""

    fact_shape: str
    prompt_template: str
    fallback_template: str
    field_mapping: tuple[tuple[str, str], ...]
    detail_formatter: str


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    name: str
    description: str
    domain: str
    business_object: str
    inputs: tuple[InputDescriptor, ...]
    # Runbook 14: optional aliases / examples for recall. Default empty tuple
    # so existing capabilities without these fields still load successfully.
    aliases: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    side_effect: str = ""
    narrative: NarrativeConfig | None = None
    intent_config: IntentConfig | None = None


@dataclass(frozen=True)
class IntentCatalog:
    capabilities: tuple[CapabilityDescriptor, ...]
    capability_ids: frozenset[str]
    # Declarative intent extraction: semantic-type catalog loaded atomically
    # with the capability declarations. Default empty for backward compatibility.
    semantic_types: SemanticTypeCatalog = field(default_factory=SemanticTypeCatalog)

    def find(self, capability_id: str) -> CapabilityDescriptor | None:
        for cap in self.capabilities:
            if cap.capability_id == capability_id:
                return cap
        return None


def _parse_narrative(raw: object) -> NarrativeConfig | None:
    """Parse an optional narrative declaration; None when absent or malformed."""
    if not isinstance(raw, dict):
        return None
    try:
        field_mapping_raw = raw.get("fieldMapping") or {}
        field_mapping = tuple(
            (str(k), str(v)) for k, v in field_mapping_raw.items()
        ) if isinstance(field_mapping_raw, dict) else ()
        return NarrativeConfig(
            fact_shape=str(raw["factShape"]),
            prompt_template=str(raw["promptTemplate"]),
            fallback_template=str(raw["fallbackTemplate"]),
            field_mapping=field_mapping,
            detail_formatter=str(raw.get("detailFormatter", "none")),
        )
    except (KeyError, TypeError):
        return None


def _parse_matcher(raw: object) -> MatcherConfig | None:
    if not isinstance(raw, dict) or "kind" not in raw:
        return None
    return MatcherConfig(
        kind=str(raw["kind"]),
        pattern=str(raw["pattern"]) if raw.get("pattern") is not None else None,
        value=str(raw["value"]) if raw.get("value") is not None else None,
        ref=str(raw["ref"]) if raw.get("ref") is not None else None,
        ignore_case=bool(raw.get("ignoreCase", False)),
        scan=str(raw.get("scan", "first")),
    )


def _parse_condition(raw: object) -> ConditionConfig | None:
    if not isinstance(raw, dict) or "field" not in raw or "equals" not in raw:
        return None
    return ConditionConfig(field=str(raw["field"]), equals=str(raw["equals"]))


def _parse_extraction(raw: object) -> ExtractionConfig | None:
    if not isinstance(raw, dict):
        return None
    matchers = tuple(m for m in (_parse_matcher(x) for x in raw.get("matchers") or []) if m)
    if not matchers:
        return None
    return ExtractionConfig(
        matchers=matchers,
        priority=int(raw.get("priority", 0)),
        excludes=tuple(str(x) for x in raw.get("excludes") or []),
        resolver=str(raw.get("resolver", "text")),
        when=_parse_condition(raw.get("when")),
        required_when=_parse_condition(raw.get("requiredWhen")),
        reask_suspect=bool(raw.get("reaskSuspect", False)),
    )


def _parse_clarify_case(raw: object) -> ClarifyCase | None:
    if not isinstance(raw, dict) or "text" not in raw:
        return None
    return ClarifyCase(
        missing=frozenset(str(m) for m in raw.get("missing") or []),
        text=str(raw["text"]),
    )


def _parse_clarify_prompt(raw: object) -> ClarifyPromptConfig | None:
    if not isinstance(raw, dict):
        return None
    cases = tuple(
        c for c in (_parse_clarify_case(x) for x in raw.get("cases") or []) if c
    )
    fallback = raw.get("fallback")
    fallback_template = (
        str(fallback["template"])
        if isinstance(fallback, dict) and fallback.get("template") is not None
        else None
    )
    if not cases and fallback_template is None:
        return None
    return ClarifyPromptConfig(cases=cases, fallback_template=fallback_template)


def _parse_require_any(raw: object) -> RequireAnyConfig | None:
    if not isinstance(raw, dict) or "inputs" not in raw or "missingName" not in raw:
        return None
    return RequireAnyConfig(
        inputs=tuple(str(x) for x in raw.get("inputs") or []),
        missing_name=str(raw["missingName"]),
    )


def _parse_intent_block(raw: object) -> IntentConfig | None:
    """Parse the optional capability-level intent declaration block.

    Locale maps (fieldNames / clarifyPrompt) are converted to nested tuples of
    pairs to stay hashable/frozen, matching the NarrativeConfig.field_mapping
    convention.
    """
    if not isinstance(raw, dict) or "intentName" not in raw:
        return None
    primary_keywords = tuple(str(k) for k in raw.get("primaryKeywords") or [])
    if not primary_keywords:
        return None
    raw_field_names = raw.get("fieldNames")
    field_names = tuple(
        (str(locale), tuple((str(k), str(v)) for k, v in fields_map.items()))
        for locale, fields_map in (
            raw_field_names.items() if isinstance(raw_field_names, dict) else ()
        )
        if isinstance(fields_map, dict)
    )
    raw_clarify = raw.get("clarifyPrompt")
    clarify_prompt = tuple(
        (str(locale), config)
        for locale, config in (
            (locale, _parse_clarify_prompt(body))
            for locale, body in (
                raw_clarify.items() if isinstance(raw_clarify, dict) else ()
            )
            if isinstance(body, dict)
        )
        if config is not None
    )
    raw_trigger = raw.get("triggerKeywords")
    return IntentConfig(
        intent_name=str(raw["intentName"]),
        primary_keywords=primary_keywords,
        weak_keywords=tuple(str(k) for k in raw.get("weakKeywords") or []),
        trigger_keywords=(
            tuple(str(k) for k in raw_trigger)
            if isinstance(raw_trigger, list)
            else None
        ),
        field_names=field_names,
        clarify_prompt=clarify_prompt,
        require_any=_parse_require_any(raw.get("requireAny")),
    )


def _parse_value_filters(raw: object) -> ValueFilters:
    if not isinstance(raw, dict):
        return ValueFilters()
    min_length = raw.get("minLength")
    return ValueFilters(
        min_length=int(min_length) if min_length is not None else None,
        not_in=tuple(str(x) for x in raw.get("notIn") or []),
        prefix_blacklist=tuple(str(x) for x in raw.get("prefixBlacklist") or []),
        to_upper_compare=bool(raw.get("toUpperCaseCompare", False)),
        to_upper_output=bool(raw.get("toUpperCaseOutput", False)),
    )


def _parse_semantic_type_catalog(raw: object) -> SemanticTypeCatalog:
    """Parse the semantic-type catalog document; empty catalog when malformed."""
    if not isinstance(raw, dict):
        return SemanticTypeCatalog(entries=())
    entries = []
    for entry in raw.get("semanticTypes") or []:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        matchers = tuple(
            m for m in (_parse_matcher(x) for x in entry.get("matchers") or []) if m
        )
        if not matchers:
            continue
        entries.append(
            SemanticTypeEntry(
                entry_id=str(entry["id"]),
                priority=int(entry.get("priority", 0)),
                matchers=matchers,
                filters=_parse_value_filters(entry.get("filters")),
            )
        )
    return SemanticTypeCatalog(entries=tuple(entries))


def _load_semantic_types(registry_dir: Path) -> SemanticTypeCatalog:
    """Load semantic-types.yaml from the same registry dir; degrade to empty."""
    catalog_path = registry_dir / "semantic-types.yaml"
    try:
        with open(catalog_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return SemanticTypeCatalog(entries=())
    return _parse_semantic_type_catalog(data)


def _empty_catalog() -> IntentCatalog:
    return IntentCatalog(capabilities=(), capability_ids=frozenset())


def _resolve_registry_path(repo_root: str | None) -> str | None:
    # 1. 显式 repo_root：只在该路径找，找不到不回退（显式路径应被尊重）
    if repo_root:
        candidate = Path(repo_root) / "registry" / "capabilities.yaml"
        return str(candidate) if candidate.exists() else None

    # 2. SAP_NEXUS_AGENT_ROOT 环境变量
    env_root = os.environ.get("SAP_NEXUS_AGENT_ROOT")
    if env_root:
        candidate = Path(env_root) / "registry" / "capabilities.yaml"
        if candidate.exists():
            return str(candidate)

    # 3. 从本文件位置向上查找 registry/ 目录
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        candidate = parent / "registry" / "capabilities.yaml"
        if candidate.exists():
            return str(candidate)

    # 4. cwd 兜底
    candidate = Path.cwd() / "registry" / "capabilities.yaml"
    if candidate.exists():
        return str(candidate)

    return None


def load_intent_catalog(repo_root: str | None = None) -> IntentCatalog:
    """从 registry/capabilities.yaml 读取 active capability，构建 IntentCatalog。

    同一次调用中原子加载 registry/semantic-types.yaml（同一根目录解析）；
    目录缺失或不可读时 catalog 降级为空条目（不抛异常，与整体非抛出风格一致）。
    找不到 registry 文件时返回空 catalog（不抛异常，LLM 路径自然降级为 unsupported）。
    """
    registry_path = _resolve_registry_path(repo_root)
    if registry_path is None:
        return _empty_catalog()

    semantic_types = _load_semantic_types(Path(registry_path).parent)

    try:
        with open(registry_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return _empty_catalog()

    if not isinstance(data, dict):
        return _empty_catalog()

    raw_capabilities = data.get("capabilities") or []
    descriptors: list[CapabilityDescriptor] = []
    for cap in raw_capabilities:
        if not isinstance(cap, dict):
            continue
        if cap.get("status") != "active":
            continue
        inputs = tuple(
            InputDescriptor(
                name=inp["name"],
                semantic_name=inp.get("semanticName", inp["name"]),
                semantic_type=inp.get("semanticType", ""),
                binding_kind=inp.get("bindingKind"),
                required=bool(inp.get("required", False)),
                type=inp.get("type", "string"),
                min_length=inp.get("minLength"),
                max_length=inp.get("maxLength"),
                pattern=inp.get("pattern"),
                extraction=_parse_extraction(inp.get("extraction")),
            )
            for inp in (cap.get("inputs") or [])
            if isinstance(inp, dict) and "name" in inp
        )
        # Runbook 14: optional aliases / examples. Backward compatible —
        # absent fields yield empty tuples.
        raw_aliases = cap.get("aliases") or []
        aliases = tuple(str(a) for a in raw_aliases) if isinstance(raw_aliases, list) else ()
        raw_examples = cap.get("examples") or []
        examples = tuple(str(e) for e in raw_examples) if isinstance(raw_examples, list) else ()
        raw_governance = cap.get("governance")
        side_effect = raw_governance.get("sideEffect", "") if isinstance(raw_governance, dict) else ""
        narrative = _parse_narrative(cap.get("narrative"))
        intent_config = _parse_intent_block(cap.get("intent"))
        descriptors.append(
            CapabilityDescriptor(
                capability_id=cap["capabilityId"],
                name=cap.get("name", ""),
                description=cap.get("description", ""),
                domain=cap.get("domain", ""),
                business_object=cap.get("businessObject", ""),
                inputs=inputs,
                aliases=aliases,
                examples=examples,
                side_effect=side_effect,
                narrative=narrative,
                intent_config=intent_config,
            )
        )

    return IntentCatalog(
        capabilities=tuple(descriptors),
        capability_ids=frozenset(d.capability_id for d in descriptors),
        semantic_types=semantic_types,
    )
