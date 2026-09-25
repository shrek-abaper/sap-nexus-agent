"""Codegen: registry/capabilities.yaml -> SKOS labels + SHACL input shapes.

The registry YAML is the single authored source; this module projects it into
standard semantic artifacts at build time:

  skos-capabilities.ttl   one Concept per capability (pref/alt labels)
  shacl-inputs.ttl        one NodeShape per constrained input
  manifest.json           sha256 of the files

Deterministic: fixed ordering, no timestamps, no blank nodes. The same input
always produces the same bytes and hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ONTOLOGY_NAMESPACE = "https://sap-nexus-agent.local/ontology#"
GENERATED_DIR_DEFAULT = "generated"

_PREFIXES = (
    f"@prefix sapnexus: <{ONTOLOGY_NAMESPACE}> .\n"
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
)

_DATATYPE_FOR_TYPE = {
    "string": "xsd:string",
    "number": "xsd:decimal",
}


@dataclass(frozen=True)
class Bundle:
    skos: str
    shacl: str

    def manifest(self) -> dict[str, str]:
        return {
            "skos-capabilities.ttl": sha256(self.skos),
            "shacl-inputs.ttl": sha256(self.shacl),
        }


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _literal(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    return f'"{escaped}"'


def _plain_keywords(cap: dict) -> list[str]:
    """Strong trigger keywords that are plain text; regex-shaped are excluded."""
    intent = cap.get("intent") or {}
    keywords = [
        *intent.get("primaryKeywords", []),
        *(intent.get("triggerKeywords") or intent.get("primaryKeywords", [])),
    ]
    plain = [kw for kw in keywords if re.fullmatch(r"[\w一-鿿 ]+", kw)]
    return sorted(set(plain))


def build_skos(capabilities: list[dict]) -> str:
    lines = [
        _PREFIXES,
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n",
        "sapnexus:CapabilityConceptScheme a skos:ConceptScheme ;",
        '    skos:prefLabel "SAP Nexus Capability Concept Scheme" .',
    ]
    for cap in capabilities:
        node = cap["ontologyIri"]
        alt_labels = sorted(set(cap.get("aliases", [])) | set(_plain_keywords(cap)))
        label_lines = [f'    skos:prefLabel {_literal(cap["name"])}@en']
        for alias in alt_labels:
            label_lines.append(f"    skos:altLabel {_literal(alias)}")
        if cap.get("description"):
            label_lines.append(f"    skos:definition {_literal(cap['description'])}")
        for example in cap.get("examples", []):
            label_lines.append(f"    skos:example {_literal(example)}")
        label_lines.append("    skos:topConceptOf sapnexus:CapabilityConceptScheme")
        label_lines.append("    skos:inScheme sapnexus:CapabilityConceptScheme")
        for index in range(len(label_lines) - 1):
            label_lines[index] += " ;"
        label_lines[-1] += " ."
        lines.append(f"{node} a skos:Concept ;")
        lines.extend(label_lines)
    return "\n".join(lines) + "\n"


def _shape_iri(capability_id: str, input_name: str) -> str:
    safe = capability_id.replace(".", "_").replace("-", "_")
    return f"sapnexus:Shape.{safe}.{input_name}"


def build_shacl(capabilities: list[dict]) -> str:
    lines = [
        _PREFIXES,
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n",
    ]
    for cap in capabilities:
        for inp in cap.get("inputs", []):
            constraints: list[str] = []
            datatype = _DATATYPE_FOR_TYPE.get(inp.get("type"))
            if datatype:
                constraints.append(f"    sh:datatype {datatype}")
            if inp.get("minLength") is not None:
                constraints.append(f"    sh:minLength {int(inp['minLength'])}")
            if inp.get("maxLength") is not None:
                constraints.append(f"    sh:maxLength {int(inp['maxLength'])}")
            if inp.get("pattern"):
                constraints.append(f"    sh:pattern {_literal(inp['pattern'])}")
            if not constraints:
                continue

            shape = _shape_iri(cap["capabilityId"], inp["name"])
            header = [
                f"{shape} a sh:NodeShape ;",
                f"    sh:name {_literal(inp['name'])} ;",
                f"    sapnexus:forCapability {cap['ontologyIri']} ;",
                f"    sapnexus:forInput {_literal(inp['name'])} ;",
                f"    sapnexus:required {'true' if inp.get('required') else 'false'} ;",
            ]
            lines.extend(header)
            lines.append(" ;\n".join(constraints) + " .")
    return "\n".join(lines) + "\n"


def build_bundle(capabilities: list[dict]) -> Bundle:
    return Bundle(skos=build_skos(capabilities), shacl=build_shacl(capabilities))


def load_capabilities(registry_path: Path) -> list[dict]:
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    return registry["capabilities"]


def is_in_sync(generated_dir: Path) -> tuple[bool, list[str]]:
    """Check committed artifacts match a fresh build from the registry."""
    problems: list[str] = []
    repo_root = generated_dir.parents[1] if generated_dir.name == "generated" else None
    if repo_root is None:
        return False, ["unexpected generated dir layout"]

    capabilities = load_capabilities(repo_root / "registry" / "capabilities.yaml")
    bundle = build_bundle(capabilities)

    for name, content in (
        ("skos-capabilities.ttl", bundle.skos),
        ("shacl-inputs.ttl", bundle.shacl),
    ):
        path = generated_dir / name
        if not path.exists():
            problems.append(f"{name}: missing")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"{name}: out of sync with registry")

    manifest_path = generated_dir / "manifest.json"
    expected_manifest = bundle.manifest()
    if not manifest_path.exists():
        problems.append("manifest.json: missing")
    elif json.loads(manifest_path.read_text(encoding="utf-8")) != expected_manifest:
        problems.append("manifest.json: out of sync")

    return not problems, problems
