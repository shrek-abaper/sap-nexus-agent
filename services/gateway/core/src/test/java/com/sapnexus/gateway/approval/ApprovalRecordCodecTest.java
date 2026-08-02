package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;

import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ApprovalRecordCodecTest {

    @Test
    void approvalRecordRoundTripPreservesAllFields() {
        ApprovalRecord record = new ApprovalRecord(
                "appr-001",
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001", "plant", "1000"),
                "user@example.com",
                Instant.parse("2026-08-02T10:00:00Z"),
                Instant.parse("2026-08-02T10:10:00Z"),
                "approved"
        );
        String json = ApprovalRecordCodec.toJson(record);
        ApprovalRecord restored = ApprovalRecordCodec.fromJson(json);
        assertEquals(record, restored);
    }

    @Test
    void leaseInfoRoundTrip() {
        LeaseInfo lease = new LeaseInfo("worker-42", Instant.parse("2026-08-02T10:01:00Z"));
        String json = ApprovalRecordCodec.toJson(lease);
        LeaseInfo restored = ApprovalRecordCodec.leaseFromJson(json);
        assertEquals(lease, restored);
    }

    @Test
    void leaseOutcomeThreeStatesArePatternMatchable() {
        LeaseOutcome claimed = new LeaseOutcome.Claimed();
        LeaseOutcome rejected = new LeaseOutcome.Rejected("worker-1", Instant.parse("2026-08-02T10:01:00Z"));
        LeaseOutcome forceClaimed = new LeaseOutcome.ForceClaimed("worker-1");

        assertInstanceOf(LeaseOutcome.Claimed.class, claimed);
        assertInstanceOf(LeaseOutcome.Rejected.class, rejected);
        assertInstanceOf(LeaseOutcome.ForceClaimed.class, forceClaimed);

        // Java 17 does not support pattern switch (finalized in Java 21); use instanceof
        // pattern matching (finalized in Java 16) to verify the same subtypes + accessors.
        String result;
        if (forceClaimed instanceof LeaseOutcome.Claimed) {
            result = "claimed";
        } else if (forceClaimed instanceof LeaseOutcome.Rejected r) {
            result = "rejected:" + r.holder();
        } else if (forceClaimed instanceof LeaseOutcome.ForceClaimed f) {
            result = "force:" + f.previousHolder();
        } else {
            throw new AssertionError("unexpected LeaseOutcome subtype: " + forceClaimed);
        }
        assertEquals("force:worker-1", result);
    }
}
