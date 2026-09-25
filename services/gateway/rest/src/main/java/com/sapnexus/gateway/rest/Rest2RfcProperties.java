package com.sapnexus.gateway.rest;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Gateway-controlled endpoint catalog for the pure-ABAP rest2rfc SICF gateway.
 *
 * <p>Property prefix: {@code sap.gateway.rest2rfc}. Endpoints are keyed by the
 * binding {@code systemRef}. Any blank field is resolved from environment
 * variables ({@code SAP_REST2RFC_*}, falling back to the shared {@code SAP_*}
 * values); credentials MUST NOT appear in the registry or these properties in
 * deployed form.
 */
@ConfigurationProperties(prefix = "sap.gateway.rest2rfc")
public class Rest2RfcProperties {

    private Map<String, Endpoint> systems = new LinkedHashMap<>();

    public Map<String, Endpoint> getSystems() {
        return systems;
    }

    public void setSystems(Map<String, Endpoint> systems) {
        this.systems = systems == null ? new LinkedHashMap<>() : systems;
    }

    public static class Endpoint {
        private String baseUrl;
        private String path;
        private String client;
        private String user;
        private String password;

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getPath() {
            return path;
        }

        public void setPath(String path) {
            this.path = path;
        }

        public String getClient() {
            return client;
        }

        public void setClient(String client) {
            this.client = client;
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
    }
}
