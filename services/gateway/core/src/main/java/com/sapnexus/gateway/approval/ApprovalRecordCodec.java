package com.sapnexus.gateway.approval;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

/**
 * Jackson helpers for {@link ApprovalRecord} and {@link LeaseInfo} JSON round-trip.
 * Instant is serialized as an ISO-8601 string (WRITE_DATES_AS_TIMESTAMPS disabled).
 *
 * <p>{@code FAIL_ON_UNKNOWN_PROPERTIES} is disabled because {@link ApprovalRecord}
 * exposes a no-arg {@code isExecuted()} method that Jackson serializes as an
 * {@code executed} property; ignoring it on deserialization preserves round-trip
 * equality (the field is derived from {@code status}).
 */
final class ApprovalRecordCodec {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    private ApprovalRecordCodec() {}

    static String toJson(ApprovalRecord record) {
        try {
            return MAPPER.writeValueAsString(record);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize ApprovalRecord", e);
        }
    }

    static ApprovalRecord fromJson(String json) {
        try {
            return MAPPER.readValue(json, ApprovalRecord.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to deserialize ApprovalRecord", e);
        }
    }

    static String toJson(LeaseInfo lease) {
        try {
            return MAPPER.writeValueAsString(lease);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to serialize LeaseInfo", e);
        }
    }

    static LeaseInfo leaseFromJson(String json) {
        try {
            return MAPPER.readValue(json, LeaseInfo.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to deserialize LeaseInfo", e);
        }
    }
}
