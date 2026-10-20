package com.sapnexus.gateway.masterdata;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Gateway-controlled configuration for the master-data projection pool.
 *
 * <p>Resolved from the environment ({@code PG_MASTERDATA_JDBC_URL},
 * {@code PG_MASTERDATA_USER}, {@code PG_MASTERDATA_PASSWORD},
 * {@code PG_MASTERDATA_MAPPINGS_PATH}), never from the registry. The binding
 * only names a credential reference ({@code pg-masterdata-readonly}); the
 * actual secret material lives here, Gateway-side.
 */
@ConfigurationProperties(prefix = "pg.masterdata")
public class PgMasterdataProperties {

    private String jdbcUrl = System.getenv().getOrDefault(
            "PG_MASTERDATA_JDBC_URL", "jdbc:postgresql://127.0.0.1:5432/sap_nexus_dev");
    private String user = System.getenv().getOrDefault("PG_MASTERDATA_USER", "");
    private String password = System.getenv().getOrDefault("PG_MASTERDATA_PASSWORD", "");
    private String mappingsPath = System.getenv().getOrDefault(
            "PG_MASTERDATA_MAPPINGS_PATH", "../master-data/physical-mappings.yaml");
    private int maximumPoolSize = 4;
    private long connectionTimeoutMs = 3000;
    private long queryTimeoutSeconds = 5;

    public String getJdbcUrl() {
        return jdbcUrl;
    }

    public void setJdbcUrl(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    public String getUser() {
        return user;
    }

    public void setUser(String user) {
        this.user = user;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    public String getMappingsPath() {
        return mappingsPath;
    }

    public void setMappingsPath(String mappingsPath) {
        this.mappingsPath = mappingsPath;
    }

    public int getMaximumPoolSize() {
        return maximumPoolSize;
    }

    public void setMaximumPoolSize(int maximumPoolSize) {
        this.maximumPoolSize = maximumPoolSize;
    }

    public long getConnectionTimeoutMs() {
        return connectionTimeoutMs;
    }

    public void setConnectionTimeoutMs(long connectionTimeoutMs) {
        this.connectionTimeoutMs = connectionTimeoutMs;
    }

    public long getQueryTimeoutSeconds() {
        return queryTimeoutSeconds;
    }

    public void setQueryTimeoutSeconds(long queryTimeoutSeconds) {
        this.queryTimeoutSeconds = queryTimeoutSeconds;
    }
}
