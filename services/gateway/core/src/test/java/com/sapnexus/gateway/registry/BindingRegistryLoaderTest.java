package com.sapnexus.gateway.registry;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class BindingRegistryLoaderTest {

    @TempDir
    Path tempDir;

    @Test
    void loadsRestJsonFields() throws Exception {
        Path file = tempDir.resolve("executor-bindings.yaml");
        Files.writeString(file, """
                version: 1
                bindings:
                  - bindingId: sap.fi.ap.get-open-items-rest2rfc
                    type: REST_JSON
                    systemRef: sap-sat
                    method: POST
                    pathTemplate: /sap/bc/rest2rfc
                    request:
                      mode: dynamic
                    response:
                      mode: dynamic
                    auth:
                      type: basic
                      credentialRef: sap-rest2rfc
                    constraints:
                      sideEffect: none
                      timeoutMs: 30000
                """);

        BindingRegistry registry = new BindingRegistryLoader().load(file);

        assertThat(registry.version()).isEqualTo(1);
        BindingDefinition binding = registry.find("sap.fi.ap.get-open-items-rest2rfc").orElseThrow();
        assertThat(binding.type()).isEqualTo("REST_JSON");
        assertThat(binding.systemRef()).isEqualTo("sap-sat");
        assertThat(binding.method()).isEqualTo("POST");
        assertThat(binding.pathTemplate()).isEqualTo("/sap/bc/rest2rfc");
        assertThat(binding.request()).containsEntry("mode", "dynamic");
        assertThat(binding.response()).containsEntry("mode", "dynamic");
        assertThat(binding.auth()).containsEntry("credentialRef", "sap-rest2rfc");
        assertThat(binding.constraints()).containsEntry("sideEffect", "none");
    }

    @Test
    void loadsOdataBindingWithoutRestFields() throws Exception {
        Path file = tempDir.resolve("executor-bindings.yaml");
        Files.writeString(file, """
                version: 1
                bindings:
                  - bindingId: sap.mm.purchaseorder.list-odata
                    type: ODATA
                    serviceRef: API_PURCHASEORDER_PROCESS_SRV
                    entitySet: A_PurchaseOrder
                    method: GET
                    filterMapping:
                      poNumber: PurchaseOrder
                    topLimit: 50
                    constraints:
                      sideEffect: none
                """);

        BindingRegistry registry = new BindingRegistryLoader().load(file);

        BindingDefinition binding = registry.find("sap.mm.purchaseorder.list-odata").orElseThrow();
        assertThat(binding.serviceRef()).isEqualTo("API_PURCHASEORDER_PROCESS_SRV");
        assertThat(binding.topLimit()).isEqualTo(50);
        assertThat(binding.systemRef()).isNull();
        assertThat(binding.pathTemplate()).isNull();
    }
}
