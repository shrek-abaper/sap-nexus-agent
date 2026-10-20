package com.sapnexus.gateway.masterdata;

/**
 * Fixed parameterized query text for the master-data projection. Values are
 * bound only through {@code ?} parameters; LIKE metacharacters in user input
 * are escaped so input stays a literal substring. No table, column, or sort
 * fragment ever comes from a request, the registry, or the model.
 */
final class MasterdataQueries {

    static final int MAX_LIMIT = 50;
    static final int TRIGRAM_MIN_QUERY_LENGTH = 3;
    static final double TRIGRAM_THRESHOLD = 0.2;

    static final String ENTITIES_IN_SCOPE =
            "SELECT source_system, client, object_type, canonical_code, status, attributes::text,"
                    + " snapshot_id, loaded_at::text, source_extracted_at::text"
                    + " FROM md.v_entity_current"
                    + " WHERE object_type = ? AND source_system = ANY(?) AND client = ANY(?)";

    // Visibility semantics: exclude only entities that HAVE extension rows
    // for the field and none matches; entities with no extension rows for the
    // field stay visible (an unimported extension is not unavailability).
    static final String CODES_BY_ORG_SCOPE =
            "SELECT canonical_code FROM md.v_entity_current"
                    + " WHERE object_type = ? AND ("
                    + "   canonical_code IN ("
                    + "     SELECT canonical_code FROM md.v_entity_org_scope_current"
                    + "     WHERE object_type = ? AND org_field = ? AND org_value = ?)"
                    + "   OR NOT EXISTS ("
                    + "     SELECT 1 FROM md.v_entity_org_scope_current o"
                    + "     WHERE o.object_type = ? AND o.org_field = ?"
                    + "       AND o.canonical_code = md.v_entity_current.canonical_code)"
                    + " )";

    static final String DESCRIPTIONS =
            "SELECT canonical_code, language, description, is_official"
                    + " FROM md.v_entity_description_current"
                    + " WHERE object_type = ? AND canonical_code = ANY(?)";

    static final String ORG_SCOPES =
            "SELECT canonical_code, org_field, org_value FROM md.v_entity_org_scope_current"
                    + " WHERE object_type = ? AND canonical_code = ANY(?) ORDER BY org_field, org_value";

    static final String CURRENT_SNAPSHOT =
            "SELECT snapshot_id, source_extracted_at::text, loaded_at::text FROM md.v_snapshot_current"
                    + " WHERE object_type = ? AND source_system = ANY(?) AND client = ANY(?)"
                    + " ORDER BY loaded_at DESC LIMIT 1";

    static final String CODES_BY_EXACT_LABEL =
            "SELECT canonical_code FROM md.v_entity_description_current"
                    + " WHERE object_type = ? AND lower(description) = lower(?)";

    static final String CODES_BY_ALIAS =
            "SELECT canonical_code FROM md.v_entity_alias_current"
                    + " WHERE object_type = ? AND active AND lower(alias) = lower(?)";

    static final String CODES_BY_SUBSTRING =
            "SELECT canonical_code FROM md.v_entity_description_current"
                    + " WHERE object_type = ? AND description ILIKE ? ESCAPE '\\'";

    static final String CODES_BY_TRIGRAM =
            "SELECT canonical_code, max(similarity(description, ?)) AS score"
                    + " FROM md.v_entity_description_current"
                    + " WHERE object_type = ? AND description % ?"
                    + " GROUP BY canonical_code ORDER BY score DESC LIMIT " + MAX_LIMIT;

    static final String ENTITY_BY_KEY =
            "SELECT source_system, client, object_type, canonical_code, status, attributes::text"
                    + " FROM md.v_entity_current"
                    + " WHERE object_type = ? AND source_system = ? AND client = ? AND canonical_code = ?";

    private MasterdataQueries() {
    }

    /** Escapes LIKE metacharacters so user input stays a literal substring. */
    static String likeEscape(String value) {
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}
