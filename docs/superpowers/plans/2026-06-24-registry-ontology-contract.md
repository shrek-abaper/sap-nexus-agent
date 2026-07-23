---
change: sap-nexus-registry-ontology-contract
design-doc: docs/superpowers/specs/2026-06-24-registry-ontology-contract-design.md
base-ref: 1fc4a4606b18062b0e70ac2aa1815787cef0484f
archived-with: 2026-06-24-sap-nexus-registry-ontology-contract
---

# Registry Ontology Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Registry / OWL contract gate for semantic capability validation, multi-executor binding readiness, governance consistency, OWL identity, and eval linkage without changing existing Gateway / Agent runtime behavior.

**Architecture:** Use a staged compatibility split. Keep current `registry/capabilities.yaml` runtime-compatible while adding contract artifacts around it: executor binding schema, optional binding catalog, offline OWL skeletons, and a local validator. The validator is the release gate; future runtime dispatcher work remains deferred.

**Tech Stack:** Python 3.12 stdlib, pytest, JSON Schema files as versioned contracts, YAML files constrained to the project's existing simple subset, OWL/RDF XML skeletons as offline artifacts.

## Global Constraints

- Respond in Chinese for user-facing progress; use English for code, identifiers, filenames, env vars, comments, and commit messages.
- Work on the currently checked-out branch; do not create, switch, or rename branches unless explicitly selected by the user.
- Do not commit unless explicitly asked.
- Preserve existing Gateway / Registry execution / JCo connectivity / Python Agent CallPlan / LLM intent adapter / Workbench Console behavior.
- Do not implement Knowledge Graph runtime, Graph Registry backend, OData Gateway, CDS / ADT Gateway, REST JSON Gateway, SAP write Action, arbitrary HTTP client, arbitrary URL execution, or LLM-generated JSON payload execution.
- Do not add `.env`, SAP passwords, destination config, tokens, LLM API keys, raw live LLM responses, or runtime traces.
- Prefer stdlib for the registry validator in this change; do not add PyYAML/jsonschema unless explicitly approved.

archived-with: 2026-06-24-sap-nexus-registry-ontology-contract
---

## File Structure

- Create `schemas/executor-binding.schema.json`: contract schema for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` binding shapes.
- Create or modify `schemas/capability.schema.json`: keep existing compatibility fields and add release-gate metadata only if required by implementation.
- Modify `registry/capabilities.yaml`: add the minimal contract metadata needed for `bindingId` / eval linkage while preserving current `executor` runtime fields.
- Create `registry/executor-bindings.yaml`: allowlisted binding catalog if the implementation needs a separate file to prove semantic/technical split.
- Create `registry/README.md`: document contract boundary and validation command.
- Create `ontology/sapnexus-core.owl`: offline core identity skeleton.
- Create `ontology/mm-inventory.owl`: offline MM inventory identity skeleton.
- Create `ontology/README.md`: document offline-only OWL boundary.
- Create `scripts/validate-registry-contract.py`: deterministic contract validator CLI.
- Create `agent/tests/test_registry_contract.py` or `tests/registry/test_registry_contract.py`: registry-focused tests; use `agent/tests/` if import/path setup is simpler.
- Modify `docs/runbooks/04-registry-ontology-contract.md`, `docs/runbooks/README.md`, and `docs/wiki/sap-nexus-agent-implementation-roadmap.md`: closeout/progress and verification command updates.
- Modify `openspec/changes/sap-nexus-registry-ontology-contract/tasks.md`: check off tasks only after each task's verification passes.

### Task 1: Contract Shape And Compatibility

**Files:**
- Modify: `registry/capabilities.yaml`
- Create: `registry/executor-bindings.yaml`
- Create: `schemas/executor-binding.schema.json`
- Modify: `schemas/capability.schema.json` if compatibility metadata is required

**Interfaces:**
- Consumes: current `MM.Inventory.GetAvailability` fields from `registry/capabilities.yaml`.
- Produces: `executorBinding.bindingId` or equivalent metadata on the capability; allowlisted binding entry `sap.mm.inventory.md04-stock-req-list`; schema enum for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, `REST_JSON`.

- [x] **Step 1: Add failing contract fixture expectation**

Create `agent/tests/test_registry_contract.py` with an initial test that expects the current registry to expose a binding identity. Use this shape so the first run fails until the registry/binding artifact exists:

```python
from pathlib import Path

from scripts.validate_registry_contract import load_registry_contract, validate_registry_contract


def test_inventory_capability_has_stable_binding_identity():
    contract = load_registry_contract(Path("registry/capabilities.yaml"))
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert errors == []
    inventory = contract.capability("MM.Inventory.GetAvailability")
    assert inventory.executor_binding_id == "sap.mm.inventory.md04-stock-req-list"
    assert inventory.executor_type == "JCO_RFC"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py::test_inventory_capability_has_stable_binding_identity -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.validate_registry_contract'` or missing binding metadata.

- [x] **Step 3: Add minimal contract artifacts**

Update `registry/capabilities.yaml` by adding compatibility-safe metadata under the existing capability:

```yaml
    executorBinding:
      type: JCO_RFC
      bindingId: sap.mm.inventory.md04-stock-req-list
    evalLinkage:
      evalFile: evals/inventory_availability_cases.yaml
      caseIds:
        - happy-path
        - missing-plant
        - missing-material
        - invalid-plant
        - unknown-intent
        - gateway-sensitive-failure
        - user-rfc-name
```

Create `registry/executor-bindings.yaml`:

```yaml
version: 1
bindings:
  - bindingId: sap.mm.inventory.md04-stock-req-list
    type: JCO_RFC
    rfcName: BAPI_MATERIAL_STOCK_REQ_LIST
    allowedImports:
      - MATERIAL_LONG
      - MATERIAL
      - PLANT
      - MRP_AREA
      - UNIT
    allowedOutputs:
      - MRP_IND_LINES
      - RETURN
    constraints:
      sideEffect: none
      timeoutMs: 30000
```

Create `schemas/executor-binding.schema.json` with allowed executor types and protocol-specific required fields. Include `REST_JSON` fields `systemRef`, `method`, `pathTemplate`, `request`, `response`, `auth.credentialRef`, and `constraints.sideEffect`.

- [x] **Step 4: Run compatibility checks**

Run: `scripts/verify-agent-callplan-evidence.sh`

Expected: existing 41 passed / 1 skipped Agent test shape, Eval passed 7/7, OpenSpec passed. The exact pytest timing may vary.

- [x] **Step 5: Mark task progress**

After the contract artifacts and compatibility checks pass, update `openspec/changes/sap-nexus-registry-ontology-contract/tasks.md` to check 1.1, 1.2, and 1.3.

### Task 2: Deterministic Validator And Registry Tests

**Files:**
- Create: `scripts/validate-registry-contract.py`
- Create or modify: `agent/tests/test_registry_contract.py`
- Create: `agent/tests/fixtures/registry/*.yaml` if fixture files are clearer than inline strings

**Interfaces:**
- Produces: `load_registry_contract(path: Path) -> RegistryContract`; `validate_registry_contract(contract: RegistryContract, repo_root: Path) -> list[str]`; CLI `python scripts/validate-registry-contract.py registry/capabilities.yaml`.
- Consumes: `registry/capabilities.yaml`, `registry/executor-bindings.yaml`, `ontology/*.owl`, `evals/inventory_availability_cases.yaml`.

- [x] **Step 1: Write failing validator tests**

Extend `agent/tests/test_registry_contract.py` with these tests before implementing full validation:

```python
from pathlib import Path

from scripts.validate_registry_contract import load_registry_contract, validate_registry_contract


def test_function_with_write_side_effect_fails(tmp_path):
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(Path("registry/capabilities.yaml").read_text().replace("sideEffect: none", "sideEffect: write"), encoding="utf-8")
    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert any("Function capability must have sideEffect=none" in error for error in errors)


def test_action_without_human_approval_fails(tmp_path):
    text = Path("registry/capabilities.yaml").read_text()
    text = text.replace("kind: Function", "kind: Action")
    text = text.replace("requiresApproval: false", "requiresApproval: false")
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(text, encoding="utf-8")
    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert any("Action capability must require human approval" in error for error in errors)


def test_missing_eval_linkage_fails(tmp_path):
    text = Path("registry/capabilities.yaml").read_text()
    text = text.replace("    evalLinkage:\n      evalFile: evals/inventory_availability_cases.yaml\n      caseIds:\n        - happy-path\n        - missing-plant\n        - missing-material\n        - invalid-plant\n        - unknown-intent\n        - gateway-sensitive-failure\n        - user-rfc-name\n", "")
    registry = tmp_path / "capabilities.yaml"
    registry.write_text(text, encoding="utf-8")
    contract = load_registry_contract(registry)
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert any("evalLinkage" in error for error in errors)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`

Expected: FAIL until validator functions and metadata checks exist.

- [x] **Step 3: Implement the validator module**

Create `scripts/validate-registry-contract.py`. Because hyphenated script names are not importable, also create package bridge files if needed:

```text
scripts/__init__.py
scripts/validate_registry_contract.py
scripts/validate-registry-contract.py
```

Use `scripts/validate-registry-contract.py` as the CLI wrapper and put importable logic in `scripts/validate_registry_contract.py`.

Implement:

```python
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
        ...


def load_registry_contract(path: Path) -> RegistryContract:
    ...


def validate_registry_contract(contract: RegistryContract, repo_root: Path) -> list[str]:
    ...
```

For YAML parsing, implement only the subset needed by repo fixtures: nested mappings, lists, scalars, booleans, integers, and strings.

- [x] **Step 4: Implement semantic checks**

Add validation for:

```text
unique capabilityId
ontologyIri starts with sapnexus:
Function sideEffect=none / requiresApproval=false / approvalPolicy=not_required
Action requiresApproval=true / approvalPolicy=human_required
executorBinding.bindingId present
bindingId exists in registry/executor-bindings.yaml
binding type is one of JCO_RFC, ODATA, CDS_ADT, CDS_ODATA, REST_JSON
active capability has evalLinkage with existing file and case IDs
```

- [x] **Step 5: Implement CLI**

`scripts/validate-registry-contract.py` should print success on no errors and print one error per line to stderr with exit code 1 when errors exist.

Run: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`

Expected: PASS and a short success message.

- [x] **Step 6: Mark task progress**

After tests and CLI pass, update `tasks.md` to check 2.1, 2.2, and 2.3.

### Task 3: OWL Skeleton And Identity Validation

**Files:**
- Create: `ontology/sapnexus-core.owl`
- Create: `ontology/mm-inventory.owl`
- Create: `ontology/README.md`
- Modify: `scripts/validate_registry_contract.py`
- Modify: `agent/tests/test_registry_contract.py`

**Interfaces:**
- Produces: OWL identity strings that the validator can find by substring/XML text: `sapnexus:Function`, `sapnexus:ExecutorBinding`, `sapnexus:RestJsonBinding`, `sapnexus:MM_Inventory_GetAvailability`.
- Consumes: `ontologyIri` from Registry.

- [x] **Step 1: Write failing OWL identity test**

Add:

```python
def test_inventory_ontology_identity_exists():
    contract = load_registry_contract(Path("registry/capabilities.yaml"))
    errors = validate_registry_contract(contract, repo_root=Path("."))
    assert errors == []
    owl_text = Path("ontology/mm-inventory.owl").read_text(encoding="utf-8")
    assert "sapnexus:MM_Inventory_GetAvailability" in owl_text
```

Run: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py::test_inventory_ontology_identity_exists -v`

Expected: FAIL until OWL files exist and validator checks them.

- [x] **Step 2: Add core OWL skeleton**

Create `ontology/sapnexus-core.owl` with RDF/XML or simple OWL XML that includes classes for `Skill`, `Function`, `Action`, `Capability`, `BusinessObject`, `ReasoningFact`, `RecommendationPlan`, `ApprovalRecord`, `ActionResult`, `ExecutorBinding`, `TechnicalAdapter`, `JcoRfcBinding`, `ODataBinding`, `CdsAdtBinding`, `CdsODataBinding`, `RestJsonBinding`, `ExternalSystem`, `CredentialReference`, `JsonRequestSchema`, `JsonResponseSchema`, and `ResponseMapping`.

- [x] **Step 3: Add MM inventory OWL skeleton**

Create `ontology/mm-inventory.owl` with terms for `Material`, `Plant`, `InventoryStock`, `AvailableQuantity`, and individual/class identity `sapnexus:MM_Inventory_GetAvailability`.

- [x] **Step 4: Add OWL README**

Create `ontology/README.md` stating:

```markdown
# SAP Nexus Ontology Skeleton

These OWL files are offline semantic contract scaffolding. Agent, Workbench, and Gateway runtime do not load GraphDB, Jena, Neo4j, or an OWL runtime in this change.
```

- [x] **Step 5: Extend validator identity check**

Update validator to ensure every `ontologyIri` value appears in `ontology/*.owl` text. Use plain text lookup; do not add RDF parser dependency.

- [x] **Step 6: Mark task progress**

After OWL tests and validator pass, update `tasks.md` to check 3.1, 3.2, and 3.3.

### Task 4: Documentation And Traceability

**Files:**
- Create: `registry/README.md`
- Modify: `docs/runbooks/04-registry-ontology-contract.md`
- Modify: `docs/runbooks/README.md`
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`
- Modify: `openspec/changes/sap-nexus-registry-ontology-contract/tasks.md`

**Interfaces:**
- Consumes: final validator command, test command, scope boundaries, and artifact paths.
- Produces: user-facing continuation and verification instructions.

- [x] **Step 1: Document Registry contract command**

Create `registry/README.md` with:

```markdown
# SAP Nexus Capability Registry

`capabilities.yaml` is the semantic capability registry. Runtime compatibility for the current `JCO_RFC` Gateway is preserved, while contract validation also checks executor binding readiness, OWL identity, governance, and eval linkage.

Run:

```bash
.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml
```

This command must not require SAP credentials, LLM credentials, network access, runtime traces, or Gateway startup.
```

- [x] **Step 2: Update runbook 04**

Update `docs/runbooks/04-registry-ontology-contract.md` version/date/status and add a session note listing implemented contract artifacts and verification commands. Keep non-goals explicit.

- [x] **Step 3: Update runbook index**

Update `docs/runbooks/README.md` for the current status of runbook `04` only. Do not mark archived until verify/archive actually completes.

- [x] **Step 4: Update roadmap**

Update `docs/wiki/sap-nexus-agent-implementation-roadmap.md` Phase 4 status with contract artifacts and note that runtime pilots remain deferred.

- [x] **Step 5: Mark task progress**

After docs are updated, update `tasks.md` to check 4.1, 4.2, and 4.3.

### Task 5: Verification And Closeout Prep

**Files:**
- Modify: `openspec/changes/sap-nexus-registry-ontology-contract/tasks.md`
- No source files unless verification exposes a bug.

**Interfaces:**
- Consumes: validator, tests, docs, OpenSpec artifacts.
- Produces: verified build-stage readiness for Comet verify.

- [x] **Step 1: Run registry validator**

Run: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`

Expected: success message and exit code 0.

- [x] **Step 2: Run registry-focused tests**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`

Expected: all registry contract tests pass.

- [x] **Step 3: Run existing Agent regression**

Run: `scripts/verify-agent-callplan-evidence.sh`

Expected: pytest passes, Eval passed 7/7, OpenSpec strict validation passes. PostHog network flush errors are non-blocking only if exit code is 0.

- [x] **Step 4: Run OpenSpec validation**

Run: `openspec validate --all --strict`

Expected: all specs and active change validation pass.

- [x] **Step 5: Check git status and sensitive files**

Run: `git status --short`

Expected: changes limited to project contract artifacts/docs/OpenSpec files plus user-confirmed external `.codex` changes. Confirm no `.env`, credentials, tokens, SAP destination config, LLM API keys, raw live responses, or runtime traces are included.

- [x] **Step 6: Mark final build tasks**

Update `tasks.md` to check 5.1, 5.2, 5.3, and 5.4 only after verification succeeds.

## Self-Review

- Spec coverage: Tasks cover Registry contract, semantic/binding split, multi-executor readiness, REST JSON safety, governance, OWL identity, and eval linkage.
- Placeholder scan: No TODO/TBD placeholders remain in executable task steps.
- Type consistency: Validator names are consistent: importable module `scripts.validate_registry_contract`, CLI wrapper `scripts/validate-registry-contract.py`.
