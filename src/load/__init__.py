"""Stage 2 — load standardised node/edge CSVs into Neo4j via BioCypher.

``adapters.py`` turns the standardised CSVs into BioCypher node/edge tuples;
``run.py`` drives BioCypher against ``config/schema_config.yaml`` to write the Neo4j
admin-import files. See docs/dev_guides/kg_data_model.md.
"""
