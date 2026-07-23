package com.sapnexus.gateway.trace;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;

public class TraceWriter {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private final Path traceFile;

    public TraceWriter(Path traceFile) {
        this.traceFile = traceFile;
    }

    public void write(TraceRecord record) {
        try {
            Path parent = traceFile.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            String json = OBJECT_MAPPER.writeValueAsString(record) + System.lineSeparator();
            Files.writeString(traceFile, json, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException e) {
            throw new UncheckedIOException("Unable to write trace record", e);
        }
    }
}
