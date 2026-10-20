-- 0001_master_data.sql — master-data read projection for entity resolution.
--
-- Role: PostgreSQL is a READ-ONLY retrieval projection of SAP master data,
-- not a second authoritative source (spec: master-data-snapshot-store).
-- SAP attributes arrive only through the governed snapshot importer; the
-- resolution API never rewrites them. Local aliases stay separate from
-- official descriptions.
--
-- Isolated test/dev environments only: creating extensions and roles in
-- production is NOT authorized by this change.
--
-- Apply (dev, peer auth):
--   psql -d sap_nexus_dev -f db/migrations/0001_master_data.sql

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS md;

-- ---------------------------------------------------------------------------
-- Snapshot registry. One snapshot per (source_system, client, object_type)
-- batch. Readers only ever see status='active'; publishing flips status
-- inside the importer's single transaction, so no reader sees a half batch.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS md.snapshot (
    snapshot_id          text PRIMARY KEY,
    source_system        text NOT NULL,
    client               text NOT NULL,
    object_type          text NOT NULL,
    snapshot_kind        text NOT NULL CHECK (snapshot_kind IN ('full')),
    coverage             jsonb NOT NULL,
    content_hash         text NOT NULL,
    -- NULL means the source extraction time is unknown; the importer must
    -- never substitute the load time for it.
    source_extracted_at  timestamptz,
    loaded_at            timestamptz NOT NULL DEFAULT now(),
    status               text NOT NULL CHECK (status IN ('loading', 'active', 'superseded')),
    -- Idempotency: re-importing the same batch content is a no-op.
    UNIQUE (source_system, client, object_type, content_hash)
);

-- ---------------------------------------------------------------------------
-- Entity identity: (source_system, client, object_type, canonical_code).
-- canonical_code stays a string: leading zeros, alphanumerics, decimal
-- specs and special characters are preserved as imported.
-- attributes holds the CLOSED set of distinguishing attributes declared by
-- ontology/entity-resolution.yaml for that object type (validated by the
-- importer); it is not an open enterprise EAV platform.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS md.entity (
    snapshot_id     text NOT NULL REFERENCES md.snapshot (snapshot_id),
    source_system   text NOT NULL,
    client          text NOT NULL,
    object_type     text NOT NULL,
    canonical_code  text NOT NULL CHECK (length(canonical_code) > 0),
    status          text NOT NULL CHECK (status IN ('active', 'inactive')),
    attributes      jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (snapshot_id, source_system, client, object_type, canonical_code)
);

-- Multi-language descriptions. Multiple language rows are views of ONE
-- entity, never separate entities.
CREATE TABLE IF NOT EXISTS md.entity_description (
    snapshot_id     text NOT NULL,
    source_system   text NOT NULL,
    client          text NOT NULL,
    object_type     text NOT NULL,
    canonical_code  text NOT NULL,
    language        text NOT NULL,
    description     text NOT NULL CHECK (length(description) > 0),
    is_official     boolean NOT NULL DEFAULT false,
    PRIMARY KEY (snapshot_id, source_system, client, object_type, canonical_code, language),
    FOREIGN KEY (snapshot_id, source_system, client, object_type, canonical_code)
        REFERENCES md.entity (snapshot_id, source_system, client, object_type, canonical_code)
);

-- Governed aliases with provenance, scope, and validity. A user picking a
-- candidate in one conversation never writes a public alias.
CREATE TABLE IF NOT EXISTS md.entity_alias (
    snapshot_id     text NOT NULL,
    source_system   text NOT NULL,
    client          text NOT NULL,
    object_type     text NOT NULL,
    canonical_code  text NOT NULL,
    alias           text NOT NULL CHECK (length(alias) > 0),
    alias_source    text NOT NULL,
    scope           text NOT NULL,
    active          boolean NOT NULL DEFAULT true,
    PRIMARY KEY (snapshot_id, source_system, client, object_type, canonical_code, alias),
    FOREIGN KEY (snapshot_id, source_system, client, object_type, canonical_code)
        REFERENCES md.entity (snapshot_id, source_system, client, object_type, canonical_code)
);

-- Organizational availability (e.g. material-plant extension), separated
-- from identity.
CREATE TABLE IF NOT EXISTS md.entity_org_scope (
    snapshot_id     text NOT NULL,
    source_system   text NOT NULL,
    client          text NOT NULL,
    object_type     text NOT NULL,
    canonical_code  text NOT NULL,
    org_field       text NOT NULL,
    org_value       text NOT NULL,
    PRIMARY KEY (snapshot_id, source_system, client, object_type, canonical_code, org_field, org_value),
    FOREIGN KEY (snapshot_id, source_system, client, object_type, canonical_code)
        REFERENCES md.entity (snapshot_id, source_system, client, object_type, canonical_code)
);

CREATE INDEX IF NOT EXISTS entity_description_trgm
    ON md.entity_description USING GIN (description gin_trgm_ops);
CREATE INDEX IF NOT EXISTS entity_alias_trgm
    ON md.entity_alias USING GIN (alias gin_trgm_ops);
CREATE INDEX IF NOT EXISTS entity_org_scope_lookup
    ON md.entity_org_scope (object_type, org_field, org_value);

-- ---------------------------------------------------------------------------
-- Current-snapshot views: the only read surface. The search account is
-- granted SELECT on these views and nothing else.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW md.v_entity_current AS
SELECT e.*, s.loaded_at, s.source_extracted_at
FROM md.entity e
JOIN md.snapshot s ON s.snapshot_id = e.snapshot_id
WHERE s.status = 'active';

CREATE OR REPLACE VIEW md.v_entity_description_current AS
SELECT d.*
FROM md.entity_description d
JOIN md.snapshot s ON s.snapshot_id = d.snapshot_id
WHERE s.status = 'active';

CREATE OR REPLACE VIEW md.v_entity_alias_current AS
SELECT a.*
FROM md.entity_alias a
JOIN md.snapshot s ON s.snapshot_id = a.snapshot_id
WHERE s.status = 'active';

CREATE OR REPLACE VIEW md.v_entity_org_scope_current AS
SELECT o.*
FROM md.entity_org_scope o
JOIN md.snapshot s ON s.snapshot_id = o.snapshot_id
WHERE s.status = 'active';

CREATE OR REPLACE VIEW md.v_snapshot_current AS
SELECT snapshot_id, source_system, client, object_type, coverage,
       source_extracted_at, loaded_at
FROM md.snapshot
WHERE status = 'active';

COMMIT;

-- Least-privilege read role and grants live in 0002_master_data_roles.sql
-- (requires an admin role with CREATEROLE, run via the DB owner).
