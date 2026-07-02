"""Stage 1 — standardise raw per-entity TSVs into graph-ready node/edge CSVs.

The mapping (which raw table feeds which node/edge, how columns are renamed and
cleaned) is declared in ``mapping.py``; ``run.py`` is the engine that applies it.
See docs/dev_guides/kg_data_model.md for the target schema.
"""
