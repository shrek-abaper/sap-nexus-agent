package com.sapnexus.gateway.registry;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Extraction metadata is agent-side data: the gateway loader must be indifferent
 * to it (registry-ontology-contract delta, "Gateway ignores extraction metadata
 * safely").
 */
class ExtractionMetadataIndifferenceTest {
    @TempDir
    Path tempDir;

    private static final String REGISTRY_WITH_METADATA = """
            version: 2
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
                intent:
                  intentName: inventory_availability
                  primaryKeywords: ['库存']
                  weakKeywords: ['有没有']
                  triggerKeywords: ['库存', '有没有']
                  clarifyPrompt:
                    zh-CN:
                      fallback:
                        template: '请提供: {fields}'
                inputs:
                  - name: material
                    semanticName: materialNumber
                    semanticType: sapnexus:MaterialNumber
                    required: true
                    type: string
                    sapParameter: MATERIAL
                    extraction:
                      matchers:
                        - kind: semanticType
                          ref: MaterialNumber
                      priority: 10
                      excludes: [plant]
                      resolver: text
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
                  sideEffect: none
                  requiresApproval: false
                  approvalPolicy: not_required
                  dataClassification: internal
                  auditRequired: true
            """;

    private static final String REGISTRY_WITHOUT_METADATA = """
            version: 2
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
                    semanticName: materialNumber
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
                  rfcName: BAPI_MATERIAL_STOCK_REQ_LIST
                  inputMapping:
                    material: MATERIAL
                  outputMapping:
                    returnMessages: RETURN
                executorBinding:
                  type: JCO_RFC
                  bindingId: sap.mm.inventory.md04-stock-req-list
                governance:
                  sideEffect: none
                  requiresApproval: false
                  approvalPolicy: not_required
                  dataClassification: internal
                  auditRequired: true
            """;

    @Test
    void loadingExtractionMetadataLeavesRegistryUnchanged() throws Exception {
        CapabilityRegistry loadedWith = new CapabilityRegistryLoader()
                .load(writeRegistry("with-meta.yaml", REGISTRY_WITH_METADATA));
        CapabilityRegistry loadedWithout = new CapabilityRegistryLoader()
                .load(writeRegistry("without-meta.yaml", REGISTRY_WITHOUT_METADATA));

        assertThat(loadedWith.version()).isEqualTo(loadedWithout.version());
        assertThat(loadedWith.allCapabilities())
                .map(CapabilityDefinition::capabilityId)
                .containsExactlyElementsOf(loadedWithout.allCapabilities().stream()
                        .map(CapabilityDefinition::capabilityId).toList());
        assertThat(loadedWith).isEqualTo(loadedWithout);
    }

    @Test
    void realRegistryWithExtractionMetadataLoads() {
        // The repository registry carries extraction metadata after tasks.md 1.5.
        CapabilityRegistry loaded = new CapabilityRegistryLoader().load(projectRegistry());

        assertThat(loaded.allCapabilities()).hasSize(3);
        assertThat(loaded.enabledCapabilities()).hasSize(3);
    }

    private Path writeRegistry(String fileName, String yaml) throws Exception {
        Path file = tempDir.resolve(fileName);
        Files.writeString(file, yaml);
        return file;
    }

    private Path projectRegistry() {
        Path dir = Path.of(System.getProperty("user.dir"));
        while (dir != null && !Files.exists(dir.resolve("registry/capabilities.yaml"))) {
            dir = dir.getParent();
        }
        if (dir == null) {
            throw new IllegalStateException(
                    "registry/capabilities.yaml not found from " + System.getProperty("user.dir"));
        }
        return dir.resolve("registry/capabilities.yaml");
    }
}
