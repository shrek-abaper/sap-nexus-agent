"""Change Impact Analysis.

Read-only propagation of a change (a business rule or a semantic type) to the
capabilities, fact types, and active in-flight approvals it affects.

The graph is derived deterministically from the registry and the business-rule
catalog:

    rule --scope.capabilityId--> capability
    capability --outputs.factTypeRef--> factType
    factType --satisfiableByFactType--> downstream capability

A semantic-type change enters at every capability taking that type as an input.
This is the "impact analysis" segment of change propagation: it never recomputes
state and never performs IO. Active approvals are supplied by the caller rather
than read from a store, so the analysis stays pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


def _local(curie: str | None) -> str:
    """Local name of a sapnexus: CURIE (or already-local string)."""
    if not curie:
        return ""
    return curie.split(":", 1)[1] if ":" in curie else curie


@dataclass(frozen=True)
class ImpactGraph:
    # capability <-> fact type adjacency, keyed by local names
    cap_to_facts: dict[str, set[str]]
    fact_to_caps: dict[str, set[str]]
    cap_input_types: dict[str, set[str]]   # capability -> input semantic types
    rule_to_cap: dict[str, str]            # rule local id -> capability

    def analyze(
        self,
        *,
        rule_id: str = "",
        semantic_type: str = "",
        active_approvals: Iterable[Any] = (),
    ) -> "ImpactReport":
        seeds: set[str] = set()
        entry_fact_types: set[str] = set()

        if rule_id:
            rule_local = _local(rule_id)
            cap = self.rule_to_cap.get(rule_local)
            if cap:
                seeds.add(cap)

        if semantic_type:
            type_local = _local(semantic_type)
            for cap, types in self.cap_input_types.items():
                if type_local in types:
                    seeds.add(cap)

        # Transitive closure over capability -> factType -> capability.
        affected_caps: set[str] = set()
        affected_facts: set[str] = set()
        frontier = set(seeds)
        while frontier:
            cap = frontier.pop()
            if cap in affected_caps:
                continue
            affected_caps.add(cap)
            for fact in self.cap_to_facts.get(cap, ()):  # noqa: RET503
                if fact in affected_facts:
                    continue
                affected_facts.add(fact)
                for downstream in self.fact_to_caps.get(fact, ()):
                    if downstream not in affected_caps:
                        frontier.add(downstream)

        affected_approvals = [
            self._approval_ref(record)
            for record in active_approvals
            if self._approval_capability(record) in affected_caps
        ]
        return ImpactReport(
            affected_capabilities=sorted(affected_caps),
            affected_fact_types=sorted(affected_facts),
            affected_approvals=affected_approvals,
        )

    @staticmethod
    def _approval_capability(record: Any) -> str:
        cap = getattr(record, "capability_id", None)
        if cap is None and isinstance(record, dict):
            cap = record.get("capabilityId")
        return str(cap or "")

    @staticmethod
    def _approval_ref(record: Any) -> str:
        ref = getattr(record, "approval_id", None)
        if ref is None and isinstance(record, dict):
            ref = record.get("approvalId")
        return str(ref or "")


@dataclass(frozen=True)
class ImpactReport:
    affected_capabilities: list[str]
    affected_fact_types: list[str]
    affected_approvals: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "affected_capabilities": self.affected_capabilities,
            "affected_fact_types": self.affected_fact_types,
            "affected_approvals": self.affected_approvals,
        }


def build_impact_graph(repo_root: Path) -> ImpactGraph:
    """Derive the impact graph from registry + business-rule catalog."""
    registry = yaml.safe_load(
        (repo_root / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    rules_doc = yaml.safe_load(
        (repo_root / "ontology" / "business-rules.yaml").read_text(encoding="utf-8")
    )

    cap_to_facts: dict[str, set[str]] = {}
    cap_input_types: dict[str, set[str]] = {}
    fact_consumer_inputs: dict[str, set[str]] = {}

    for cap in registry["capabilities"]:
        cap_id = str(cap["capabilityId"])
        facts = {
            _local(out.get("factTypeRef"))
            for out in cap.get("outputs", ())
            if out.get("factTypeRef")
        }
        cap_to_facts[cap_id] = facts

        input_types = {
            _local(inp.get("semanticType")) for inp in cap.get("inputs", ())
        }
        cap_input_types[cap_id] = input_types

        # An input that is satisfiable by a fact type makes this capability a
        # downstream consumer of that fact type.
        for inp in cap.get("inputs", ()):
            fact_source = inp.get("satisfiableByFactType")
            if fact_source:
                fact_consumer_inputs.setdefault(
                    _local(fact_source), set()
                ).add(cap_id)

    rule_to_cap = {
        _local(rule.get("ruleId")): str(
            (rule.get("scope") or {}).get("capabilityId", "")
        )
        for rule in rules_doc.get("rules", ())
    }

    return ImpactGraph(
        cap_to_facts=cap_to_facts,
        fact_to_caps=fact_consumer_inputs,
        cap_input_types=cap_input_types,
        rule_to_cap=rule_to_cap,
    )
