# Traditional ingest — symbol / Entrez → Ensembl gene-id mapping

Deferred from the traditional-format ingest epic (#44).

## Scope cut

v1 requires expression matrices to arrive keyed by **Ensembl gene ids**. The
matrix melt strips the version suffix (`ENSG…12` → `ENSG…`) so traditional genes
join the shared `Gene` dimension, and it raises a loud warning when a row key
does not look like an Ensembl accession — but it does **not** translate gene
symbols (`TP53`) or Entrez ids (`7157`) to Ensembl.

## Follow-on

Add an optional upstream mapping step (symbol/Entrez → Ensembl) so
symbol/Entrez-keyed matrices can be ingested without a manual pre-conversion.
Needs a curated mapping source (e.g. HGNC / Ensembl BioMart) and a decision on
how to handle one-to-many and unmapped keys.
