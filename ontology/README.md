# SAP Nexus Ontology Skeleton

> Layered semantic model and the role of these files: see [../docs/semantic-model.md](../docs/semantic-model.md).

These OWL files are offline semantic contract scaffolding for SAP Nexus Agent.

They provide stable names for Registry `ontologyIri` values and future ontology
governance. Agent, Workbench, and Gateway runtime do not load GraphDB, Jena,
Neo4j, or an OWL runtime in this change.

The skeleton is organized as:

- Business-object classes (`subClassOf BusinessObject`) and structural fact-row classes;
- Fact classes (`subClassOf ReasoningFact`), mirroring the Fact Type catalog;
- Object properties for the predicates declared in `fact-types.yaml`, with
  domain/range; single-valued facts are functional;
- Derived datatypes for scalar value types carried by BAPI/OData parameters
  (plant, company code, amounts, dates...), not business-object classes;
- `Function` disjoint with `Action` as the OWL mirror of the governance invariant.

The registry contract validator remains the enforcement gate; these OWL
axioms are its offline semantic mirror.

