package com.sapnexus.gateway.registry;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class CapabilityRegistryLoaderTest {
    @TempDir
    Path tempDir;

    @Test
    void loadsActiveInventoryAvailabilityCapability() throws Exception {
        Path registry = writeRegistry(validRegistry("active", "none", false, "not_required"));

        CapabilityRegistry loaded = new CapabilityRegistryLoader().load(registry);

        assertThat(loaded.enabledCapabilities()).hasSize(1);
        CapabilityDefinition capability = loaded.findEnabled("MM.Inventory.GetAvailability").orElseThrow();
        assertThat(capability.capabilityId()).isEqualTo("MM.Inventory.GetAvailability");
        assertThat(capability.kind()).isEqualTo(CapabilityKind.Function);
        assertThat(capability.executor().rfcName()).isEqualTo("BAPI_MATERIAL_STOCK_REQ_LIST");
        assertThat(capability.executorBinding().type()).isEqualTo("JCO_RFC");
        assertThat(capability.executorBinding().bindingId()).isEqualTo("sap.mm.inventory.md04-stock-req-list");
        assertThat(capability.governance().sideEffect()).isEqualTo(SideEffect.none);
    }

    @Test
    void rejectsMalformedRegistryEntry() throws Exception {
        Path registry = writeRegistry("""
                version: 1
                capabilities:
                  - capabilityId: MM.Inventory.GetAvailability
                    name: Inventory Availability
                    description: Read material availability.
                    status: active
                    kind: Function
                    domain: MM
                    businessObject: InventoryStock
                    ontologyIri: sapnexus:MM_Inventory_GetAvailability
                    semanticType: sapnexus:InventoryAvailabilityReadFunction
                    inputs:
                      - name: material
                        semanticType: sapnexus:MaterialNumber
                        required: true
                        type: string
                        sapParameter: MATERIAL
                    outputs:
                      - name: returnMessages
                        semanticType: sapnexus:SapReturnMessage
                        type: array
                        evidenceRole: executionEvidence
                    executor:
                      type: JCO_RFC
                    governance:
                      sideEffect: none
                      requiresApproval: false
                      approvalPolicy: not_required
                      dataClassification: internal
                      auditRequired: true
                """);

        assertThatThrownBy(() -> new CapabilityRegistryLoader().load(registry))
                .isInstanceOf(RegistryValidationException.class)
                .hasMessageContaining("executor.rfcName");
    }

    @Test
    void rejectsDuplicateCapabilityIds() throws Exception {
        String capability = inventoryCapability("active", "none", false, "not_required");
        Path registry = writeRegistry("""
                version: 1
                capabilities:
                %s
                %s
                """.formatted(capability.indent(2), capability.indent(2)));

        assertThatThrownBy(() -> new CapabilityRegistryLoader().load(registry))
                .isInstanceOf(RegistryValidationException.class)
                .hasMessageContaining("Duplicate capabilityId: MM.Inventory.GetAvailability");
    }

    @Test
    void excludesDisabledCapabilitiesFromCatalog() throws Exception {
        Path registry = writeRegistry(validRegistry("disabled", "none", false, "not_required"));

        CapabilityRegistry loaded = new CapabilityRegistryLoader().load(registry);

        assertThat(loaded.allCapabilities()).hasSize(1);
        assertThat(loaded.enabledCapabilities()).isEmpty();
        assertThat(loaded.findEnabled("MM.Inventory.GetAvailability")).isEmpty();
    }

    @Test
    void rejectsFunctionWithSideEffect() throws Exception {
        Path registry = writeRegistry(validRegistry("active", "write", false, "not_required"));

        assertThatThrownBy(() -> new CapabilityRegistryLoader().load(registry))
                .isInstanceOf(RegistryValidationException.class)
                .hasMessageContaining("Function capability must have sideEffect=none");
    }

    @Test
    void rejectsActionWithoutHumanApproval() throws Exception {
        Path registry = writeRegistry(validActionRegistry(false, "not_required"));

        assertThatThrownBy(() -> new CapabilityRegistryLoader().load(registry))
                .isInstanceOf(RegistryValidationException.class)
                .hasMessageContaining("Action capability must require human approval");
    }

    @Test
    void loadsOdataCapabilityWithoutRfcName() throws Exception {
        Path registry = writeRegistry("""
                version: 1
                capabilities:
                  - capabilityId: MM.PurchaseOrder.GetList
                    name: Purchase Order List
                    description: Read purchase order list via OData.
                    status: active
                    kind: Function
                    domain: MM
                    businessObject: PurchaseOrder
                    ontologyIri: sapnexus:MM_PurchaseOrder_GetList
                    semanticType: sapnexus:PurchaseOrderListReadFunction
                    inputs:
                      - name: poNumber
                        semanticType: sapnexus:PurchaseOrderNumber
                        required: false
                        type: string
                        sapParameter: PurchaseOrder
                      - name: vendor
                        semanticType: sapnexus:Supplier
                        required: false
                        type: string
                        sapParameter: Supplier
                    outputs:
                      - name: purchaseOrders
                        semanticType: sapnexus:PurchaseOrderItem
                        type: array
                        evidenceRole: primaryFact
                    executor:
                      type: ODATA
                    executorBinding:
                      type: ODATA
                      bindingId: sap.mm.purchaseorder.list-odata
                    governance:
                      sideEffect: none
                      requiresApproval: false
                      approvalPolicy: not_required
                      dataClassification: internal
                      auditRequired: true
                """);

        CapabilityRegistry loaded = new CapabilityRegistryLoader().load(registry);

        assertThat(loaded.enabledCapabilities()).hasSize(1);
        CapabilityDefinition capability = loaded.findEnabled("MM.PurchaseOrder.GetList").orElseThrow();
        assertThat(capability.executor().type()).isEqualTo("ODATA");
        assertThat(capability.executor().rfcName()).isNull();
        assertThat(capability.executorBinding().type()).isEqualTo("ODATA");
        assertThat(capability.executorBinding().bindingId()).isEqualTo("sap.mm.purchaseorder.list-odata");
    }

    @Test
    void rejectsExecutorMissingTypeOrMappings() throws Exception {
        Path registry = writeRegistry("""
                version: 1
                capabilities:
                  - capabilityId: MM.Inventory.GetAvailability
                    name: Inventory Availability
                    description: Read material availability.
                    status: active
                    kind: Function
                    domain: MM
                    businessObject: InventoryStock
                    ontologyIri: sapnexus:MM_Inventory_GetAvailability
                    semanticType: sapnexus:InventoryAvailabilityReadFunction
                    inputs:
                      - name: material
                        semanticType: sapnexus:MaterialNumber
                        required: true
                        type: string
                        sapParameter: MATERIAL
                    outputs:
                      - name: returnMessages
                        semanticType: sapnexus:SapReturnMessage
                        type: array
                        evidenceRole: executionEvidence
                    executor:
                      rfcName: BAPI_MATERIAL_STOCK_REQ_LIST
                    governance:
                      sideEffect: none
                      requiresApproval: false
                      approvalPolicy: not_required
                      dataClassification: internal
                      auditRequired: true
                """);

        assertThatThrownBy(() -> new CapabilityRegistryLoader().load(registry))
                .isInstanceOf(RegistryValidationException.class)
                .hasMessageContaining("executor.type");
    }

    private Path writeRegistry(String yaml) throws Exception {
        Path file = tempDir.resolve("capabilities.yaml");
        Files.writeString(file, yaml);
        return file;
    }

    private String validRegistry(String status, String sideEffect, boolean requiresApproval, String approvalPolicy) {
        return """
                version: 1
                capabilities:
                %s
                """.formatted(inventoryCapability(status, sideEffect, requiresApproval, approvalPolicy).indent(2));
    }

    private String validActionRegistry(boolean requiresApproval, String approvalPolicy) {
        return """
                version: 1
                capabilities:
                %s
                """.formatted(inventoryCapability("active", "write", requiresApproval, approvalPolicy)
                .replace("kind: Function", "kind: Action")
                .indent(2));
    }

    private String inventoryCapability(String status, String sideEffect, boolean requiresApproval, String approvalPolicy) {
        return """
                - capabilityId: MM.Inventory.GetAvailability
                  name: Inventory Availability
                  description: Read material availability.
                  status: %s
                  kind: Function
                  domain: MM
                  businessObject: InventoryStock
                  ontologyIri: sapnexus:MM_Inventory_GetAvailability
                  semanticType: sapnexus:InventoryAvailabilityReadFunction
                  inputs:
                    - name: material
                      semanticName: materialNumber
                      semanticType: sapnexus:MaterialNumber
                      required: true
                      type: string
                      minLength: 1
                      maxLength: 40
                      sapParameter: MATERIAL
                  outputs:
                    - name: returnMessages
                      semanticType: sapnexus:SapReturnMessage
                      type: array
                      evidenceRole: executionEvidence
                  executor:
                    type: JCO_RFC
                    rfcName: BAPI_MATERIAL_STOCK_REQ_LIST
                    inputMapping:
                      material: MATERIAL
                    outputMapping:
                      returnMessages: RETURN
                  executorBinding:
                    type: JCO_RFC
                    bindingId: sap.mm.inventory.md04-stock-req-list
                  governance:
                    sideEffect: %s
                    requiresApproval: %s
                    approvalPolicy: %s
                    dataClassification: internal
                    auditRequired: true
                """.formatted(status, sideEffect, requiresApproval, approvalPolicy);
    }
}
