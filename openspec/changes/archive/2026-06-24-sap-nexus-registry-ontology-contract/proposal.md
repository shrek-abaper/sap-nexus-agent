## Why

The current SAP Nexus Registry is sufficient for the completed `JCO_RFC` inventory vertical slice, but it still mixes semantic capability metadata with technical executor details and only validates the existing single executor shape. The next roadmap step needs a traceable contract layer that hardens Registry schema, OWL identity, governance checks, eval linkage, and future executor binding readiness without reopening runtime Gateway or Agent work.

## What Changes

- Add a Registry / OWL contract hardening capability for validating `registry/capabilities.yaml` as the semantic capability source of truth.
- Define a controlled multi-executor binding contract for `JCO_RFC`, `ODATA`, `CDS_ADT`, `CDS_ODATA`, and `REST_JSON` as schema/validator-ready shapes.
- Add contract validation for stable capability identity, `ontologyIri`, `kind`, governance, side effects, approval policy, technical binding ownership, and eval linkage.
- Add OWL skeleton coverage for SAP Nexus core concepts, MM inventory identity, executor bindings, external systems, credential references, and REST JSON mapping terms.
- Preserve existing Gateway, Python Agent CallPlan, LLM intent adapter, Workbench Console, and MD04 inventory runtime behavior.
- Do not implement OData Gateway, CDS / ADT Gateway, REST JSON Gateway, Knowledge Graph runtime, new SAP capability, SAP write action, arbitrary HTTP client, arbitrary URL execution, or LLM-generated JSON payload execution.

## Capabilities

### New Capabilities
- `registry-ontology-contract`: Defines Registry schema hardening, OWL skeleton identity, governance consistency validation, eval linkage, and multi-executor binding contract readiness including controlled `REST_JSON` readiness.

### Modified Capabilities

## Impact

- Affected areas: `registry/`, `schemas/`, `ontology/`, `scripts/`, registry tests, eval linkage, OpenSpec artifacts, and current runbook / roadmap closeout notes.
- Existing `gateway-jco/`, Python Agent orchestration, LLM adapter, Workbench Console runtime, and SAP JCo execution behavior must remain compatible and should only be touched if contract validation exposes a concrete compatibility gap.
- Verification should include registry contract validation, negative contract cases, existing Agent CallPlan/eval regression, and strict OpenSpec validation.
- No `.env`, SAP password, destination config, token, LLM API key, raw live LLM response, or generated runtime trace may be committed.
