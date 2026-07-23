package com.sapnexus.gateway.approval;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Map;
import java.util.TreeMap;
import org.springframework.stereotype.Component;

@Component
public class ParameterSnapshotHasher {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    public String hash(Map<String, ?> parameters) {
        TreeMap<String, String> canonicalParameters = new TreeMap<>();
        if (parameters != null) {
            parameters.forEach((key, value) -> canonicalParameters.put(key, String.valueOf(value)));
        }
        try {
            byte[] canonicalJson = OBJECT_MAPPER.writeValueAsBytes(canonicalParameters);
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(canonicalJson);
            return "sha256:" + java.util.HexFormat.of().formatHex(digest);
        } catch (JsonProcessingException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Unable to compute approval parameter snapshot hash", exception);
        }
    }
}
