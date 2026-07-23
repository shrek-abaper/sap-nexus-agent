package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.Map;
import org.junit.jupiter.api.Test;

class ParameterSnapshotHasherTest {

    private final ParameterSnapshotHasher hasher = new ParameterSnapshotHasher();

    @Test
    void usesCompactSortedJsonContractSharedWithAgent() {
        assertEquals(
                "sha256:21f76dfbfe6dfe21f762080ef484112cf2952974cef30741fd1931e1c6d92112",
                hasher.hash(Map.of("b", "2", "a", "1")));
    }

    @Test
    void stringifiesScalarParameterValuesBeforeHashing() {
        assertEquals(
                hasher.hash(Map.of("quantity", "10")),
                hasher.hash(Map.of("quantity", 10)));
    }
}
