## ADDED Requirements

### Requirement: Flexible intent recognition from registry capability set

The Agent SHALL derive the intent recognition capability closed set from active capabilities in the capability registry (`registry/capabilities.yaml`), rather than hardcoding a single capability. The LLM intent path SHALL dynamically inject all active capabilities' `capabilityId`, `description`, and `inputs` into the LLM prompt, and the LLM SHALL select a `capabilityId` directly from that closed set. A capability registered as `status: active` SHALL become selectable by the LLM path without any intent-recognition code change.

#### Scenario: Registered purchase order capability is selectable via natural language

- **WHEN** a user submits `查询采购订单DEMOPO1` and `MM.PurchaseOrder.GetList` is an active registered capability
- **THEN** the Agent intent recognition selects `MM.PurchaseOrder.GetList` (via LLM or rule fallback)
- **AND** extracts `poNumber=DEMOPO1` as a parameter
- **AND** the run proceeds to capability selection, CallPlan, Gateway validate, and Gateway execute for that capability
- **AND** does not return the "仅支持已注册的只读能力" unsupported message

#### Scenario: LLM selects capabilityId from dynamic registry closed set

- **WHEN** the LLM intent path runs with a registry containing both `MM.Inventory.GetAvailability` and `MM.PurchaseOrder.GetList` as active capabilities
- **THEN** the LLM prompt lists both capabilityIds with their descriptions and inputs
- **AND** the LLM returns a `capabilityId` that is a member of the active registry closed set
- **AND** a `capabilityId` not in the active registry closed set is rejected as unsupported

#### Scenario: Required parameters validated against selected capability inputs

- **WHEN** the LLM selects a capabilityId and the registry defines required inputs for that capability
- **THEN** the Agent validates that all required inputs are present
- **AND** if a required input is missing, returns a clarification identifying the missing parameter
- **AND** does not proceed to Gateway execution until required inputs are satisfied

#### Scenario: Rule fallback covers registered explicit intents when LLM unavailable

- **WHEN** the LLM is unavailable (missing configuration or connection failure) in hybrid mode
- **THEN** the Agent falls back to the unified rule parser (`parse_intent`) that recognizes both inventory and purchase order list intents
- **AND** does not fall back to an inventory-only parser
- **AND** a registered explicit-intent query (e.g. `查询采购订单DEMOPO1`) still resolves to the correct capability

#### Scenario: Newly registered active capability is auto-supported by LLM path

- **WHEN** a new capability is added to `registry/capabilities.yaml` with `status: active` and a description and inputs
- **AND** no intent-recognition code is changed
- **THEN** the LLM path can select the new capabilityId from the dynamically injected prompt
- **AND** the rule fallback does not need to know about the new capability for the LLM path to work

#### Scenario: CLI unified entry routes to any registered capability

- **WHEN** the Agent CLI entry processes a query
- **THEN** it uses the unified `run_query` entry that routes by selected capabilityId
- **AND** can route to both inventory and purchase order capabilities
- **AND** does not use an inventory-only entry that prevents purchase order routing
