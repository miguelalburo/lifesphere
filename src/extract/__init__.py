"""extract — schema-coverage-driven GDC extraction.

Emits the full field set present in each GDC payload record under true GDC
column names (no {entity}_ prefix), so the standardise engine can auto-bind
via camelCase/normalized strategies without hand-maintained allowlists.
"""
