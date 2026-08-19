from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import signal
import time
from typing import Any

import jsonschema

SUPPORTED_LOCALES = ("zh-CN",)
MAX_REGEX_LENGTH = 200
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()]*[*+])[^()]*\)[*+{]")
_BACKTRACKING_SAMPLES = ("a" * 64, "a" * 64 + "!", "a" * 32 + "b", "0" * 64)
_SAMPLE_TIME_BUDGET_SECONDS = 0.05
_FALLBACK_PROBE_SEGMENT = 12


class _RegexSearchTimeout(Exception):
    """Raised by the SIGALRM handler when a sample search blows the time budget."""


def _abort_search(signum: int, frame: Any) -> None:
    raise _RegexSearchTimeout()


def _fallback_probe_exceeds_budget(compiled: re.Pattern, sample: str) -> bool:
    """Bounded probe for contexts without SIGALRM (off main thread, non-POSIX).

    sre holds the GIL for the entire search, so neither a worker thread nor an
    after-the-fact clock check can bound a full-length run off the main thread.
    Instead run only a head+tail truncated probe: catastrophic backtracking
    cost grows geometrically with input length, so the probe exposes the
    evasive patterns the static heuristic misses without ever running a
    full-length search.
    """
    if len(sample) > 2 * _FALLBACK_PROBE_SEGMENT:
        probe = sample[:_FALLBACK_PROBE_SEGMENT] + sample[-_FALLBACK_PROBE_SEGMENT:]
    else:
        probe = sample
    started = time.perf_counter()
    compiled.search(probe)
    return time.perf_counter() - started > _SAMPLE_TIME_BUDGET_SECONDS


def _search_exceeds_budget(compiled: re.Pattern, sample: str) -> bool:
    """Run compiled.search(sample) under a hard time bound.

    A wall-clock check after the fact can never fire on a catastrophic pattern
    (the search simply never returns), so prefer SIGALRM to abort it. When
    signals are unavailable, fall back to a truncated probe instead of a full
    search (see _fallback_probe_exceeds_budget).
    """
    try:
        signal.signal(signal.SIGALRM, _abort_search)
        signal.setitimer(signal.ITIMER_REAL, _SAMPLE_TIME_BUDGET_SECONDS)
    except (AttributeError, ValueError, OSError):
        return _fallback_probe_exceeds_budget(compiled, sample)
    try:
        compiled.search(sample)
        return False
    except _RegexSearchTimeout:
        return True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def regex_backtracking_guard(pattern: str) -> str | None:
    """Compile + backtracking-safety guard (length, nested quantifiers, bounded sample timeout)."""
    if len(pattern) > MAX_REGEX_LENGTH:
        return f"regex exceeds length limit {MAX_REGEX_LENGTH}: {pattern[:60]!r}..."
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"regex does not compile: {exc}"
    if _NESTED_QUANTIFIER.search(pattern):
        return f"regex contains nested quantifiers (backtracking risk): {pattern[:60]!r}"
    for sample in _BACKTRACKING_SAMPLES:
        if _search_exceeds_budget(compiled, sample):
            return f"regex exceeds sample timeout on input of length {len(sample)}: {pattern[:60]!r}"
    return None


def load_semantic_type_catalog(repo_root: Path) -> tuple[dict[str, dict], list[str]]:
    """Load registry/semantic-types.yaml -> (entries by id, errors)."""
    path = repo_root / "registry" / "semantic-types.yaml"
    if not path.exists():
        return {}, ["semantic-type catalog missing: registry/semantic-types.yaml"]
    import yaml
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {}, [f"semantic-type catalog unreadable: {exc}"]
    entries: dict[str, dict] = {}
    errors: list[str] = []
    for raw in (doc or {}).get("semanticTypes", []) or []:
        if not isinstance(raw, dict):
            errors.append("semantic-type catalog entry must be a mapping")
            continue
        entry_id = str(raw.get("id") or "")
        if not entry_id:
            errors.append("semantic-type catalog entry requires id")
        elif entry_id in entries:
            errors.append(f"duplicate semantic-type id: {entry_id}")
        else:
            entries[entry_id] = raw
    return entries, errors


def validate_extraction_declarations(
    contract: RegistryContract,
    catalog_entries: dict[str, dict],
    repo_root: Path,
) -> list[str]:
    """Cross-field semantics for intent/extraction declarations.

    Opt-in per capability: rules fire only when a capability carries an
    `intent` block or an input `extraction` declaration. The semantic-type
    catalog itself is validated on every invocation.
    """
    errors: list[str] = []
    for entry_id, entry in catalog_entries.items():
        for matcher in (entry.get("matchers") or []) if isinstance(entry, dict) else []:
            errors.extend(
                _validate_matcher(
                    matcher,
                    catalog_entries,
                    f"semantic-type catalog entry {entry_id}",
                    require_justification=True,
                )
            )

    schema_path = repo_root / "schemas" / "extraction-declaration.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        intent_validator = jsonschema.Draft202012Validator(schema)
        extraction_validator = jsonschema.Draft202012Validator(schema["definitions"]["inputExtraction"])
    except (OSError, ValueError, KeyError) as exc:
        return [f"extraction-declaration schema unreadable: {exc}"]

    for capability in contract.capabilities:
        cap_id = capability.capability_id or "<unknown>"
        raw = capability.raw if isinstance(capability.raw, dict) else {}
        intent = raw.get("intent")
        if "intent" in raw and not isinstance(intent, dict):
            errors.append(f"{cap_id}: intent must be a mapping")
            intent = None
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
        extractions: list[tuple[str, dict]] = []
        for input_field in inputs:
            if not isinstance(input_field, dict):
                continue
            extraction = input_field.get("extraction")
            if extraction is None:
                continue
            input_name = str(input_field.get("name") or "<unknown>")
            if not isinstance(extraction, dict):
                errors.append(
                    f"{cap_id}: inputs[{input_name}].extraction must be a mapping"
                )
                continue
            extractions.append((input_name, extraction))
        if intent is None and not extractions:
            continue
        input_names = {
            str(field.get("name"))
            for field in inputs
            if isinstance(field, dict) and field.get("name")
        }
        if isinstance(intent, dict):
            for schema_error in intent_validator.iter_errors(intent):
                errors.append(f"{cap_id}: intent: {schema_error.message}")
            primary = {str(k) for k in (intent.get("primaryKeywords") or [])}
            weak = {str(k) for k in (intent.get("weakKeywords") or [])}
            overlap = sorted(primary & weak)
            if overlap:
                errors.append(
                    f"{cap_id}: weakKeywords must be disjoint from primaryKeywords: {', '.join(overlap)}"
                )
        required_fields = {
            str(field.get("name"))
            for field in inputs
            if isinstance(field, dict) and field.get("name") and field.get("required")
        }
        required_fields.update(
            name for name, extraction in extractions if extraction.get("requiredWhen")
        )
        if isinstance(intent, dict) and isinstance(intent.get("requireAny"), dict):
            missing_name = intent["requireAny"].get("missingName")
            if missing_name:
                required_fields.add(str(missing_name))
        if isinstance(intent, dict):
            errors.extend(_clarify_locale_errors(cap_id, intent, required_fields))
        for input_name, extraction in extractions:
            for schema_error in extraction_validator.iter_errors(extraction):
                errors.append(f"{cap_id}: inputs[{input_name}].extraction: {schema_error.message}")
            for matcher in extraction.get("matchers") or []:
                errors.extend(
                    _validate_matcher(matcher, catalog_entries, f"{cap_id}: inputs[{input_name}].extraction")
                )
            for condition_key in ("when", "requiredWhen"):
                condition = extraction.get(condition_key)
                if isinstance(condition, dict) and condition.get("field") not in input_names:
                    errors.append(
                        f"{cap_id}: inputs[{input_name}].extraction.{condition_key} "
                        f"references undeclared input: {condition.get('field')}"
                    )
            for excluded in extraction.get("excludes") or []:
                if excluded not in input_names:
                    errors.append(
                        f"{cap_id}: inputs[{input_name}].extraction.excludes "
                        f"references undeclared input: {excluded}"
                    )
    return errors


def count_regex_matchers(contract: RegistryContract, catalog_entries: dict[str, dict]) -> tuple[int, int]:
    """Count regex matchers: (semantic-type catalog, capability-level).

    Observable metric only (Design §3.3): a count, never a gate. The
    justification gate applies to catalog regex matchers; capability-level
    regexes remain legal but visible.
    """
    catalog_count = sum(
        1
        for entry in catalog_entries.values()
        for matcher in (entry.get("matchers") or []) if isinstance(entry, dict)
        if isinstance(matcher, dict) and matcher.get("kind") == "regex"
    )
    capability_count = 0
    for capability in contract.capabilities:
        raw = capability.raw if isinstance(capability.raw, dict) else {}
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
        for input_field in inputs:
            if not isinstance(input_field, dict):
                continue
            extraction = input_field.get("extraction")
            if not isinstance(extraction, dict):
                continue
            capability_count += sum(
                1
                for matcher in extraction.get("matchers") or []
                if isinstance(matcher, dict) and matcher.get("kind") == "regex"
            )
    return catalog_count, capability_count


def _validate_matcher(matcher: Any, catalog_entries: dict[str, dict], context: str, require_justification: bool = False) -> list[str]:
    """Resolve semanticType refs and guard every inline regex/keyword pattern."""
    if not isinstance(matcher, dict):
        return [f"{context}: matcher must be a mapping"]
    if matcher.get("kind") == "semanticType":
        ref = matcher.get("ref")
        if ref not in catalog_entries:
            return [f"{context}: semanticType ref not found in catalog: {ref}"]
        return []
    if require_justification and matcher.get("kind") == "regex":
        justification = matcher.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            return [f"{context}: regex matcher requires a non-empty justification (escape hatch)"]
    pattern = matcher.get("pattern")
    if isinstance(pattern, str):
        guard_error = regex_backtracking_guard(pattern)
        if guard_error:
            return [f"{context}: {guard_error}"]
    return []


def _clarify_locale_errors(cap_id: str, intent: dict[str, Any], required_fields: set[str]) -> list[str]:
    """Every supported locale must cover each required input (case.missing or fallback)."""
    errors: list[str] = []
    clarify = intent.get("clarifyPrompt")
    clarify = clarify if isinstance(clarify, dict) else {}
    for locale in SUPPORTED_LOCALES:
        prompt = clarify.get(locale)
        if not isinstance(prompt, dict):
            errors.append(
                f"{cap_id}: clarifyPrompt missing locale {locale} "
                f"for required inputs: {', '.join(sorted(required_fields))}"
            )
            continue
        fallback = prompt.get("fallback")
        has_fallback = isinstance(fallback, dict) and bool(fallback.get("template"))
        strategy = prompt.get("strategy")
        covered: set[str] = set()
        for case in prompt.get("cases") or []:
            if isinstance(case, dict):
                covered.update(str(name) for name in case.get("missing") or [])
        if strategy is not None:
            # groupByBindingKind renders every required input of a group; with
            # a single userUtterance group (all current declarations) that is
            # every required input of the capability.
            covered.update(required_fields)
        missing = sorted(
            name for name in required_fields if name not in covered and not has_fallback
        )
        if missing:
            errors.append(
                f"{cap_id}: clarifyPrompt[{locale}] missing coverage for required inputs: {', '.join(missing)}"
            )
    return errors


@dataclass(frozen=True)
class CapabilityEntry:
    raw: dict[str, Any]
    capability_id: str
    kind: str
    ontology_iri: str
    executor_type: str
    executor_binding_id: str


@dataclass(frozen=True)
class RegistryContract:
    capabilities: list[CapabilityEntry]

    def capability(self, capability_id: str) -> CapabilityEntry:
        for capability in self.capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise KeyError(capability_id)


def load_registry_contract(path: Path) -> RegistryContract:
    root = _parse_simple_yaml(path)
    entries = []
    for raw in root.get("capabilities", []):
        executor_binding = raw.get("executorBinding") or {}
        executor = raw.get("executor") or {}
        entries.append(
            CapabilityEntry(
                raw=raw,
                capability_id=str(raw.get("capabilityId") or ""),
                kind=str(raw.get("kind") or ""),
                ontology_iri=str(raw.get("ontologyIri") or ""),
                executor_type=str(executor_binding.get("type") or executor.get("type") or ""),
                executor_binding_id=str(executor_binding.get("bindingId") or ""),
            )
        )
    return RegistryContract(entries)


def validate_registry_contract(contract: RegistryContract, repo_root: Path) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    bindings = _load_bindings(repo_root / "registry" / "executor-bindings.yaml")
    for binding_id, binding in bindings.items():
        errors.extend(_validate_binding_shape(binding_id, binding))
    for capability in contract.capabilities:
        errors.extend(_validate_capability_shape(capability))
        if not capability.capability_id:
            errors.append("capabilityId is required")
        if capability.capability_id in seen:
            errors.append(f"Duplicate capabilityId: {capability.capability_id}")
        seen.add(capability.capability_id)
        if not capability.ontology_iri.startswith("sapnexus:"):
            errors.append(f"{capability.capability_id}: ontologyIri must start with sapnexus:")
        governance = capability.raw.get("governance") or {}
        if capability.kind == "Function":
            if governance.get("sideEffect") != "none":
                errors.append("Function capability must have sideEffect=none")
            if governance.get("requiresApproval") is not False:
                errors.append("Function capability must have requiresApproval=false")
            if governance.get("approvalPolicy") != "not_required":
                errors.append("Function capability must have approvalPolicy=not_required")
        if capability.kind == "Action":
            if governance.get("requiresApproval") is not True or governance.get("approvalPolicy") != "human_required":
                errors.append("Action capability must require human approval")
        if not capability.executor_binding_id:
            errors.append(f"{capability.capability_id}: executorBinding.bindingId is required")
        elif capability.executor_binding_id not in bindings:
            errors.append(f"{capability.capability_id}: bindingId not found: {capability.executor_binding_id}")
        elif bindings[capability.executor_binding_id].get("type") != capability.executor_type:
            errors.append(f"{capability.capability_id}: executorBinding.type does not match binding catalog")
        binding = bindings.get(capability.executor_binding_id, {})
        if not _ontology_contains(repo_root / "ontology", capability.ontology_iri):
            errors.append(f"{capability.capability_id}: ontologyIri not found in ontology skeleton")
        errors.extend(_validate_eval_linkage(capability, repo_root))
        errors.extend(_validate_rest_json_binding(capability, binding))
    catalog_entries, catalog_errors = load_semantic_type_catalog(repo_root)
    errors.extend(catalog_errors)
    errors.extend(validate_extraction_declarations(contract, catalog_entries, repo_root))
    return errors


def _validate_capability_shape(capability: CapabilityEntry) -> list[str]:
    errors: list[str] = []
    raw = capability.raw
    required_scalars = [
        "capabilityId",
        "name",
        "description",
        "status",
        "kind",
        "domain",
        "businessObject",
        "ontologyIri",
        "semanticType",
    ]
    for field in required_scalars:
        if not raw.get(field):
            errors.append(f"{capability.capability_id or '<unknown>'}: {field} is required")
    if raw.get("kind") not in ("Function", "Action"):
        errors.append(f"{capability.capability_id}: kind must be Function or Action")
    inputs = raw.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        errors.append(f"{capability.capability_id}: inputs are required")
    else:
        for field in inputs:
            name = field.get("name", "<unknown>") if isinstance(field, dict) else "<unknown>"
            for required in ("name", "semanticType", "required", "type"):
                if not isinstance(field, dict) or required not in field:
                    errors.append(f"{capability.capability_id}: inputs[{name}].{required} is required")
    outputs = raw.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        errors.append(f"{capability.capability_id}: outputs are required")
    else:
        for field in outputs:
            name = field.get("name", "<unknown>") if isinstance(field, dict) else "<unknown>"
            for required in ("name", "semanticType", "type", "evidenceRole"):
                if not isinstance(field, dict) or required not in field:
                    errors.append(f"{capability.capability_id}: outputs[{name}].{required} is required")
    governance = raw.get("governance")
    if not isinstance(governance, dict):
        errors.append(f"{capability.capability_id}: governance is required")
    else:
        for required in ("sideEffect", "requiresApproval", "approvalPolicy", "dataClassification", "auditRequired"):
            if required not in governance:
                errors.append(f"{capability.capability_id}: governance.{required} is required")
    errors.extend(_validate_semantic_io_fields(capability))
    return errors


def _validate_semantic_io_fields(capability: CapabilityEntry) -> list[str]:
    errors: list[str] = []
    inputs = capability.raw.get("inputs")
    if not isinstance(inputs, list):
        inputs = []
    for input_field in inputs:
        if not isinstance(input_field, dict):
            continue
        name = input_field.get("name", "<unknown>")
        binding_kind = input_field.get("bindingKind")
        if binding_kind not in ("identifier", "fact"):
            errors.append(f"{capability.capability_id}: inputs[{name}].bindingKind is required")
        if binding_kind == "fact" and not input_field.get("satisfiableByFactType"):
            errors.append(
                f"{capability.capability_id}: inputs[{name}].satisfiableByFactType is required"
            )
        if binding_kind == "identifier" and "satisfiableByFactType" in input_field:
            errors.append(
                f"{capability.capability_id}: inputs[{name}] identifier must not declare "
                "satisfiableByFactType"
            )
    outputs = capability.raw.get("outputs")
    if not isinstance(outputs, list):
        outputs = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        name = output.get("name", "<unknown>")
        if output.get("evidenceRole") == "primaryFact" and not output.get("factTypeRef"):
            errors.append(
                f"{capability.capability_id}: outputs[{name}].factTypeRef is required"
            )
    return errors


def _validate_eval_linkage(capability: CapabilityEntry, repo_root: Path) -> list[str]:
    if capability.raw.get("status") != "active":
        return []
    linkage = capability.raw.get("evalLinkage")
    if not isinstance(linkage, dict):
        return [f"{capability.capability_id}: evalLinkage is required for active capability"]
    eval_file = linkage.get("evalFile")
    case_ids = linkage.get("caseIds")
    if not eval_file:
        return [f"{capability.capability_id}: evalLinkage.evalFile is required"]
    eval_path = repo_root / str(eval_file)
    if not eval_path.exists():
        return [f"{capability.capability_id}: evalLinkage file not found: {eval_file}"]
    if not isinstance(case_ids, list) or not case_ids:
        return [f"{capability.capability_id}: evalLinkage.caseIds is required"]
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    available_ids = {str(case.get("id")) for case in payload.get("cases", [])}
    missing = [case_id for case_id in case_ids if str(case_id) not in available_ids]
    if missing:
        return [f"{capability.capability_id}: evalLinkage cases not found: {', '.join(missing)}"]
    return []


def _validate_rest_json_binding(capability: CapabilityEntry, binding: dict[str, Any]) -> list[str]:
    if binding.get("type") != "REST_JSON":
        return []
    errors: list[str] = []
    constraints = binding.get("constraints") or {}
    if capability.kind == "Function" and constraints.get("sideEffect") != "none":
        errors.append("REST_JSON Function binding must be read-only")
    if capability.kind == "Function" and binding.get("method") not in (None, "GET"):
        errors.append("REST_JSON Function binding must use GET in this contract phase")
    if "url" in binding:
        errors.append("REST_JSON binding must not contain raw url")
    auth = binding.get("auth") or {}
    for secret_key in ("token", "apiKey", "secret", "password", "connectionString"):
        if secret_key in auth:
            errors.append(f"REST_JSON auth must not contain {secret_key}")
    if "headers" in binding:
        errors.append("REST_JSON binding must not contain raw headers")
    if "payload" in binding:
        errors.append("REST_JSON binding must not contain raw payload")
    errors.extend(_find_forbidden_secret_keys(binding, "REST_JSON binding"))
    return errors


def _validate_binding_shape(binding_id: str, binding: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    binding_type = binding.get("type")
    if binding_type not in ("JCO_RFC", "ODATA", "CDS_ADT", "CDS_ODATA", "REST_JSON"):
        errors.append(f"{binding_id}: binding type is invalid")
    constraints = binding.get("constraints")
    if not isinstance(constraints, dict) or "sideEffect" not in constraints:
        errors.append(f"{binding_id}: constraints.sideEffect is required")
    if binding_type == "JCO_RFC":
        errors.extend(_require_binding_fields(binding_id, binding, ["rfcName", "allowedImports", "allowedOutputs"], "JCO_RFC"))
    if binding_type == "ODATA":
        errors.extend(_require_binding_fields(binding_id, binding, ["serviceRef", "entitySet", "method"], "ODATA"))
    if binding_type == "CDS_ADT":
        errors.extend(_require_binding_fields(binding_id, binding, ["cdsEntity", "operation"], "CDS_ADT"))
    if binding_type == "CDS_ODATA":
        errors.extend(_require_binding_fields(binding_id, binding, ["serviceRef", "entitySet", "method"], "CDS_ODATA"))
    if binding_type == "REST_JSON":
        errors.extend(_require_binding_fields(binding_id, binding, ["systemRef", "method", "pathTemplate", "request", "response", "auth"], "REST_JSON"))
        errors.extend(_validate_rest_json_binding(CapabilityEntry({}, "", "Function", "", "REST_JSON", binding_id), binding))
    return errors


def _require_binding_fields(binding_id: str, binding: dict[str, Any], fields: list[str], label: str) -> list[str]:
    errors = []
    for field in fields:
        if field not in binding:
            errors.append(f"{label} binding requires {field}")
    return errors


def _find_forbidden_secret_keys(value: Any, context: str) -> list[str]:
    forbidden = {"token", "apiKey", "secret", "connectionString", "password", "headers", "payload", "url"}
    errors: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in forbidden:
                errors.append(f"{context} must not contain {key}")
            errors.extend(_find_forbidden_secret_keys(nested, context))
    elif isinstance(value, list):
        for item in value:
            errors.extend(_find_forbidden_secret_keys(item, context))
    return errors


def _ontology_contains(ontology_dir: Path, ontology_iri: str) -> bool:
    if not ontology_iri or not ontology_dir.exists():
        return False
    for path in ontology_dir.glob("*.owl"):
        if ontology_iri in path.read_text(encoding="utf-8"):
            return True
    return False


def _load_bindings(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    root = _parse_simple_yaml(path)
    return {str(binding.get("bindingId")): binding for binding in root.get("bindings", [])}


def _parse_simple_yaml(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        text = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if text.startswith("- "):
            item_text = text[2:]
            if not isinstance(parent, list):
                raise ValueError(f"List item without list parent in {path}: {raw_line}")
            if ":" not in item_text:
                parent.append(_parse_scalar(item_text))
                continue
            item: dict[str, Any] = {}
            parent.append(item)
            if item_text:
                key, value = _split_key_value(item_text)
                if value == "":
                    # Trailing "key:" on a list-item line: the container that
                    # follows belongs to the item. Push it at a virtual indent so
                    # both the container's children and the item's sibling keys
                    # land on the right parent.
                    next_container = _next_container(lines, raw_line)
                    item[key] = next_container
                    stack.append((indent, item))
                    stack.append((indent + 2, next_container))
                else:
                    item[key] = _parse_scalar(value)
                    stack.append((indent, item))
            else:
                stack.append((indent, item))
            continue
        key, value = _split_key_value(text)
        if value == "":
            next_container: list[Any] | dict[str, Any] = _next_container(lines, raw_line)
            parent[key] = next_container
            stack.append((indent, next_container))
        else:
            parent[key] = _parse_scalar(value)
    return root


def _next_container(lines: list[str], current_line: str) -> list[Any] | dict[str, Any]:
    current_index = lines.index(current_line)
    for next_line in lines[current_index + 1 :]:
        stripped = next_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return [] if stripped.startswith("- ") else {}
    return {}


def _split_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"Expected key/value YAML line: {text}")
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.isdigit():
        return int(value)
    return value
