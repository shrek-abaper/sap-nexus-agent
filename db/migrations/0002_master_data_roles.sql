-- 0002_master_data_roles.sql — least-privilege read role for master-data search.
--
-- Requires CREATEROLE (run as the DB owner / postgres superuser):
--   sudo -u postgres psql -d sap_nexus_dev -f db/migrations/0002_master_data_roles.sql
--
-- The runtime search account must be a LOGIN role granted md_search_ro;
-- migration/import use a separate owner role. No passwords appear here:
-- login roles are provisioned by the environment's credential mechanism
-- (peer auth locally, secret injection in deployments).

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'md_search_ro') THEN
        CREATE ROLE md_search_ro NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA md TO md_search_ro;
GRANT SELECT ON md.v_entity_current TO md_search_ro;
GRANT SELECT ON md.v_entity_description_current TO md_search_ro;
GRANT SELECT ON md.v_entity_alias_current TO md_search_ro;
GRANT SELECT ON md.v_entity_org_scope_current TO md_search_ro;
GRANT SELECT ON md.v_snapshot_current TO md_search_ro;

COMMIT;
