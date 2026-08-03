from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class InputDescriptor:
    name: str
    semantic_name: str
    required: bool
    type: str


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


@dataclass(frozen=True)
class IntentCatalog:
    capabilities: tuple[CapabilityDescriptor, ...]
    capability_ids: frozenset[str]

    def find(self, capability_id: str) -> CapabilityDescriptor | None:
        for cap in self.capabilities:
            if cap.capability_id == capability_id:
                return cap
        return None


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

    找不到 registry 文件时返回空 catalog（不抛异常，LLM 路径自然降级为 unsupported）。
    """
    registry_path = _resolve_registry_path(repo_root)
    if registry_path is None:
        return _empty_catalog()

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
                required=bool(inp.get("required", False)),
                type=inp.get("type", "string"),
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
            )
        )

    return IntentCatalog(
        capabilities=tuple(descriptors),
        capability_ids=frozenset(d.capability_id for d in descriptors),
    )
