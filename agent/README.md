# SAP Nexus Agent Python MVP

Read-only Agent slice for Chinese inventory availability queries.

## Verification

```bash
python -m pip install -e agent
python -m pytest agent/tests
python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
openspec validate --all --strict
```

Fast tests and evals use fake Gateway responses by default and do not require live SAP.

`evals/inventory_availability_cases.yaml` is JSON-formatted for now so the MVP can avoid a YAML runtime dependency.
