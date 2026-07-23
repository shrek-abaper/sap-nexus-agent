---
change: sap-nexus-agent-callplan-evidence
design-doc: docs/superpowers/specs/2026-06-20-sap-nexus-agent-callplan-evidence-design.md
base-ref: ea45c3a7a1a7c9ea8a149cabd27626df80d41cb3
archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
---

# SAP Nexus Agent CallPlan Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only Python Agent slice that turns Chinese inventory queries into CallPlan, Gateway validate/execute, ReasoningFact, Chinese narration, and eval evidence.

**Architecture:** Use a small Python package under `agent/sap_nexus_agent/` with deterministic parser, closed-set selector, injectable Gateway client, fact builder, and guarded narrator. Fast tests use fake Gateway clients; live Gateway smoke remains optional.

**Tech Stack:** Python 3.12, standard library HTTP/CLI/YAML-light parser, pytest for tests, existing Java Gateway contract, OpenSpec/Comet for workflow.

## Global Constraints

- Work on the current branch; do not create or switch branches unless the user explicitly confirms later Comet build choices.
- Do not modify completed Gateway / Registry behavior for this change.
- Only support read-only `MM.Inventory.GetAvailability` in this MVP.
- Do not allow Agent-generated or user-supplied `rfcName` to reach Gateway.
- Missing `material` or `plant` must clarify before Gateway validate or execute.
- No SAP Write Action, RecommendationPlan, ML uncertainty reasoning, Knowledge Graph runtime, UI, or multi-domain orchestration.
- Do not commit `.env`, SAP password, destination config, token, or generated runtime traces.
- Fast tests and evals must not require live SAP.

archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
---

## File Structure

Create these files:

- `agent/pyproject.toml`: editable package metadata with no runtime external dependencies.
- `agent/README.md`: Agent usage and verification commands.
- `agent/sap_nexus_agent/__init__.py`: package marker and version.
- `agent/sap_nexus_agent/intent.py`: Chinese parser and missing-parameter detection.
- `agent/sap_nexus_agent/capability_selector.py`: closed-set capability selection and unsupported intent failure.
- `agent/sap_nexus_agent/call_plan.py`: CallPlan dataclass and `agentTraceId` generation.
- `agent/sap_nexus_agent/gateway_client.py`: standard-library HTTP client plus protocol shape for fake clients.
- `agent/sap_nexus_agent/execution_result.py`: Gateway validation/execution result dataclasses and parsing helpers.
- `agent/sap_nexus_agent/reasoning_fact.py`: ReasoningFact dataclass and conversion from successful ExecutionResult.
- `agent/sap_nexus_agent/narrator.py`: Chinese narration and sensitive-data redaction.
- `agent/sap_nexus_agent/orchestrator.py`: end-to-end Agent pipeline.
- `agent/sap_nexus_agent/eval.py`: YAML-like eval runner for regression cases.
- `agent/sap_nexus_agent/cli.py`: minimal CLI entrypoint.
- `agent/tests/test_intent.py`: parser and clarification tests.
- `agent/tests/test_orchestrator.py`: selection, CallPlan, Gateway ordering, and error tests.
- `agent/tests/test_reasoning_narrator.py`: fact and narration guard tests.
- `agent/tests/test_eval_runner.py`: eval runner behavior tests.
- `schemas/call-plan.schema.json`: CallPlan contract.
- `schemas/reasoning-fact.schema.json`: ReasoningFact contract.
- `evals/inventory_availability_cases.yaml`: regression cases.

Modify these files:

- `openspec/changes/sap-nexus-agent-callplan-evidence/tasks.md`: check boxes as tasks are completed.

archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
---

### Task 1: Agent Package Skeleton And Contracts

**Files:**
- Create: `agent/pyproject.toml`
- Create: `agent/README.md`
- Create: `agent/sap_nexus_agent/__init__.py`
- Create: `schemas/call-plan.schema.json`
- Create: `schemas/reasoning-fact.schema.json`
- Test: `agent/tests/test_contract_files.py`

**Interfaces:**
- Produces: importable package `sap_nexus_agent`
- Produces: schema files with top-level `type=object`, `required`, and `properties`

- [x] **Step 1: Create package metadata**

Create `agent/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "sap-nexus-agent"
version = "0.1.0"
description = "Read-only SAP Nexus Agent MVP"
requires-python = ">=3.12"
dependencies = []

[tool.setuptools.packages.find]
where = ["."]
```

- [x] **Step 2: Create package marker**

Create `agent/sap_nexus_agent/__init__.py`:

```python
__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [x] **Step 3: Add contract schemas**

Create `schemas/call-plan.schema.json` with required fields `agentTraceId`, `capabilityId`, `kind`, `parameters`, `validationPolicy`, `createdBy`, and `requiresApproval`.

Create `schemas/reasoning-fact.schema.json` with required fields `factId`, `agentTraceId`, `traceId`, `gatewayTraceId`, `domain`, `businessObject`, `predicate`, `value`, `unit`, `deterministic`, `confidence`, `source`, and `evidence`.

- [x] **Step 4: Add contract existence tests**

Create `agent/tests/test_contract_files.py`:

```python
import json
from pathlib import Path


def test_contract_files_are_valid_json():
    for path in [Path("schemas/call-plan.schema.json"), Path("schemas/reasoning-fact.schema.json")]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["type"] == "object"
        assert payload["required"]
        assert payload["properties"]
```

- [x] **Step 5: Verify package skeleton**

Run:

```bash
python -m pip install -e agent
python -m pytest agent/tests/test_contract_files.py -v
```

Expected: tests pass and no network access is required.

archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
---

### Task 2: Intent Parser And Closed-Set Selector

**Files:**
- Create: `agent/sap_nexus_agent/intent.py`
- Create: `agent/sap_nexus_agent/capability_selector.py`
- Test: `agent/tests/test_intent.py`

**Interfaces:**
- Produces: `parse_inventory_intent(text: str) -> IntentParseResult`
- Produces: `select_capability(parse_result: IntentParseResult) -> SelectionResult`
- Consumes: capability id constant `MM.Inventory.GetAvailability`

- [x] **Step 1: Write parser tests first**

Create `agent/tests/test_intent.py` with tests for:

```python
from sap_nexus_agent.capability_selector import select_capability
from sap_nexus_agent.intent import parse_inventory_intent


def test_parse_complete_chinese_inventory_query():
    result = parse_inventory_intent("DEMOA1 在 1000 还有多少可用库存？")
    assert result.intent == "inventory_availability"
    assert result.parameters == {"material": "DEMOA1", "plant": "1000"}
    assert result.missing_parameters == []


def test_parse_optional_unit():
    result = parse_inventory_intent("查一下 DEMOA1 在 1000 的 EA 可用量")
    assert result.parameters["unit"] == "EA"


def test_missing_plant_clarifies_without_selection():
    result = parse_inventory_intent("查一下 DEMOA1 的可用量")
    assert result.missing_parameters == ["plant"]


def test_missing_material_clarifies_without_selection():
    result = parse_inventory_intent("查一下 1000 工厂还有多少可用库存")
    assert result.missing_parameters == ["material"]


def test_unknown_intent_is_not_selected():
    parsed = parse_inventory_intent("帮我创建一张采购申请")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_INTENT"


def test_user_supplied_rfc_name_is_rejected():
    parsed = parse_inventory_intent("用 rfcName=BAPI_PO_CREATE1 查 DEMOA1 在 1000 的库存")
    selected = select_capability(parsed)
    assert selected.capability_id is None
    assert selected.error_type == "UNSUPPORTED_RFC_NAME"
```

- [x] **Step 2: Implement parser dataclass and extraction**

Create `intent.py` with dataclass fields `intent`, `parameters`, `missing_parameters`, `clarification`, and `contains_rfc_name`. Use conservative regex rules for material-like tokens and plant-like tokens.

- [x] **Step 3: Implement closed-set selector**

Create `capability_selector.py` with `CAPABILITY_ID = "MM.Inventory.GetAvailability"`. Return success only when intent is `inventory_availability`, no `rfcName` marker exists, and no required parameters are missing.

- [x] **Step 4: Run tests**

Run:

```bash
python -m pytest agent/tests/test_intent.py -v
```

Expected: all parser and selector tests pass.

archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
---

### Task 3: CallPlan And Gateway Orchestration

**Files:**
- Create: `agent/sap_nexus_agent/call_plan.py`
- Create: `agent/sap_nexus_agent/gateway_client.py`
- Create: `agent/sap_nexus_agent/execution_result.py`
- Create: `agent/sap_nexus_agent/orchestrator.py`
- Test: `agent/tests/test_orchestrator.py`

**Interfaces:**
- Produces: `create_call_plan(capability_id: str, parameters: dict[str, str]) -> CallPlan`
- Produces: `GatewayClientProtocol.validate(capability_id, parameters) -> ValidationResult`
- Produces: `GatewayClientProtocol.execute(capability_id, parameters) -> ExecutionResult`
- Produces: `run_inventory_query(text: str, gateway: GatewayClientProtocol) -> AgentOutcome`

- [x] **Step 1: Write orchestration tests first**

Create `agent/tests/test_orchestrator.py` with a `FakeGatewayClient` that records `validate_calls` and `execute_calls`. Test that complete requests call validate then execute, missing params call neither, validation failure stops execute, and request bodies never include `rfcName`.

- [x] **Step 2: Implement CallPlan**

Create `call_plan.py` with a frozen dataclass and `uuid.uuid4()` trace generation. Use field name `agentTraceId` in serialized dictionaries to avoid collision with Gateway-generated `traceId`.

- [x] **Step 3: Implement result dataclasses**

Create `execution_result.py` with `ValidationResult`, `ExecutionResult`, and `SapReturnMessage` dataclasses. Include `from_dict` helpers for Gateway JSON.

- [x] **Step 4: Implement Gateway client**

Create `gateway_client.py` using standard-library `urllib.request`. Send only:

```json
{"parameters": {"material": "DEMOA1", "plant": "1000", "unit": "EA"}}
```

Never send `rfcName`.

- [x] **Step 5: Implement orchestrator**

Create `orchestrator.py` so the order is parse -> select -> callplan -> validate -> execute -> structured outcome. Preserve both `agentTraceId` and Gateway `traceId`.

- [x] **Step 6: Run orchestration tests**

Run:

```bash
python -m pytest agent/tests/test_orchestrator.py -v
```

Expected: ordering and no-Gateway-call assertions pass.

archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
---

### Task 4: ReasoningFact And Chinese Narrator

**Files:**
- Create: `agent/sap_nexus_agent/reasoning_fact.py`
- Create: `agent/sap_nexus_agent/narrator.py`
- Test: `agent/tests/test_reasoning_narrator.py`

**Interfaces:**
- Consumes: successful `ExecutionResult`
- Produces: `build_availability_fact(agent_trace_id: str, result: ExecutionResult) -> ReasoningFact | None`
- Produces: `narrate_fact(fact: ReasoningFact) -> str`
- Produces: `narrate_failure(error_type: str, messages: list[str]) -> str`

- [x] **Step 1: Write fact and narrator tests first**

Create tests for successful fact creation, failed execution without success fact, Chinese fact narrative, narrative guard failure when quantity is missing, and redaction of `password=...`, `token=...`, `.env`, and `SAP_PASSWORD` markers.

- [x] **Step 2: Implement ReasoningFact**

Create a dataclass with fields from `schemas/reasoning-fact.schema.json`. Map `ExecutionResult.data.availableQuantity` to `predicate=availableQuantity`, `value`, `unit`, and evidence entries.

- [x] **Step 3: Implement narrator**

Narrate only fact fields. Example success response:

```text
物料 DEMOA1 在工厂 1000 的可用库存为 12 EA。
```

If the fact lacks quantity, raise or return `NARRATIVE_GUARD_ERROR`.

- [x] **Step 4: Run evidence tests**

Run:

```bash
python -m pytest agent/tests/test_reasoning_narrator.py -v
```

Expected: all fact, narration, and redaction tests pass.

archived-with: 2026-06-20-sap-nexus-agent-callplan-evidence
---

### Task 5: Eval Runner, CLI, Documentation, And OpenSpec Checks

**Files:**
- Create: `agent/sap_nexus_agent/eval.py`
- Create: `agent/sap_nexus_agent/cli.py`
- Create: `evals/inventory_availability_cases.yaml`
- Modify: `agent/README.md`
- Modify: `openspec/changes/sap-nexus-agent-callplan-evidence/tasks.md`

**Interfaces:**
- Produces: `python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`
- Produces: `python -m sap_nexus_agent.cli "DEMOA1 在 1000 还有多少可用库存？"`

- [x] **Step 1: Add eval cases**

Create `evals/inventory_availability_cases.yaml` with cases for happy path, missing plant, missing material, invalid plant, unknown intent, Gateway failure, and sensitive-data guard. Keep the format simple enough for a minimal parser or `json` fallback if YAML dependencies are unavailable.

- [x] **Step 2: Implement eval runner**

Implement `eval.py` to load cases, run `run_inventory_query` with fake Gateway responses, and assert expected capability, missing parameters, Gateway call counts, success/failure, and sensitive string absence.

- [x] **Step 3: Implement CLI**

Implement `cli.py` with `argparse`. Default Gateway URL should be `http://localhost:8080`. CLI should print Chinese response only, not raw credentials or destination config.

- [x] **Step 4: Document verification**

Update `agent/README.md` with:

```bash
python -m pip install -e agent
python -m pytest agent/tests
python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
openspec validate --all --strict
```

- [x] **Step 5: Run full verification**

Run:

```bash
python -m pip install -e agent
python -m pytest agent/tests
python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
openspec validate --all --strict
```

Expected: fast tests pass, eval passes, OpenSpec validation passes. PostHog telemetry errors after successful OpenSpec output are non-blocking.

- [x] **Step 6: Update OpenSpec tasks**

Check off completed tasks in `openspec/changes/sap-nexus-agent-callplan-evidence/tasks.md` only after the corresponding implementation and verification pass.
