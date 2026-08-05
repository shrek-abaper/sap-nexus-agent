package com.sapnexus.gateway.api;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;

import org.junit.jupiter.api.Test;

class CapabilityRequestPlanApprovalTest {

    @Test
    void carriesOnlyPlanAwareGuardBindingsAlongsideSemanticParameters() {
        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000"),
                "appr-plan-21",
                "sha256:parameters",
                "snapshot-21",
                "2.1.0",
                "sha256:subject-21");

        assertThat(request.registrySnapshotId()).isEqualTo("snapshot-21");
        assertThat(request.capabilityVersion()).isEqualTo("2.1.0");
        assertThat(request.approvalSubjectHash()).isEqualTo("sha256:subject-21");
        assertThat(request.technicalOverrideKeys()).isEmpty();
    }

    @Test
    void legacyConstructorsLeavePlanAwareBindingsAbsent() {
        CapabilityRequest parametersOnly = new CapabilityRequest(Map.of("material", "M001"));
        CapabilityRequest atomicApproval = new CapabilityRequest(
                Map.of("material", "M001"), "appr-legacy", "sha256:parameters");

        assertThat(parametersOnly.registrySnapshotId()).isNull();
        assertThat(parametersOnly.capabilityVersion()).isNull();
        assertThat(parametersOnly.approvalSubjectHash()).isNull();
        assertThat(atomicApproval.registrySnapshotId()).isNull();
        assertThat(atomicApproval.capabilityVersion()).isNull();
        assertThat(atomicApproval.approvalSubjectHash()).isNull();
    }
}
