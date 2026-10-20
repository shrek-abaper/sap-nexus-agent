package com.sapnexus.gateway.masterdata;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.SQLTransientException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Executes fixed parameterized queries against the projection pool. SQL text
 * comes only from {@link MasterdataQueries}; parameters are bound by
 * position. Raw SQL/connection details never escape this class.
 */
public class MasterdataQueryRunner implements AutoCloseable {

    /** Functional seam for unit tests (no live database required). */
    @FunctionalInterface
    public interface RowExecutor {
        List<Map<String, Object>> query(String sql, List<Object> params) throws SQLException;
    }

    private final HikariDataSource dataSource;
    private final long queryTimeoutSeconds;

    public MasterdataQueryRunner(PgMasterdataProperties properties) {
        HikariConfig config = new HikariConfig();
        config.setJdbcUrl(properties.getJdbcUrl());
        if (!properties.getUser().isBlank()) {
            config.setUsername(properties.getUser());
            config.setPassword(properties.getPassword());
        }
        config.setMaximumPoolSize(properties.getMaximumPoolSize());
        config.setConnectionTimeout(properties.getConnectionTimeoutMs());
        config.setPoolName("pg-masterdata-readonly");
        config.setReadOnly(true);
        this.dataSource = new HikariDataSource(config);
        this.queryTimeoutSeconds = properties.getQueryTimeoutSeconds();
    }

    public RowExecutor rowExecutor() {
        return this::query;
    }

    public List<Map<String, Object>> query(String sql, List<Object> params) throws SQLException {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setQueryTimeout((int) queryTimeoutSeconds);
            for (int i = 0; i < params.size(); i++) {
                Object param = params.get(i);
                if (param instanceof List<?> list) {
                    statement.setArray(i + 1, connection.createArrayOf("text", list.toArray()));
                } else {
                    statement.setObject(i + 1, param);
                }
            }
            try (ResultSet rs = statement.executeQuery()) {
                ResultSetMetaData meta = rs.getMetaData();
                int width = meta.getColumnCount();
                List<Map<String, Object>> rows = new ArrayList<>();
                while (rs.next()) {
                    Map<String, Object> row = new LinkedHashMap<>();
                    for (int c = 1; c <= width; c++) {
                        row.put(meta.getColumnLabel(c), rs.getObject(c));
                    }
                    rows.add(row);
                }
                return rows;
            }
        }
    }

    static boolean isUnavailable(SQLException e) {
        if (e instanceof SQLTransientException) {
            return true;
        }
        String state = e.getSQLState();
        return state != null && state.startsWith("08");
    }

    static boolean isPermissionDenied(SQLException e) {
        String state = e.getSQLState();
        return "42501".equals(state) || (state != null && state.startsWith("28"));
    }

    @Override
    public void close() {
        dataSource.close();
    }
}
