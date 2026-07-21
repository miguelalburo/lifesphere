# Traditional ingest — SnpEff `ANN` and annotators beyond VEP `CSQ`

Deferred from the traditional-format ingest epic (#44).

## Scope cut

The VCF reader derives `IS_WITHIN_GENE` edges only from a **VEP `CSQ`** INFO
field, locating the `Gene` sub-field via the `##INFO=<ID=CSQ,…Format:…>` header.
SnpEff's `ANN` field (and any other annotator's format) is **not** parsed in v1.

## Follow-on

Add support for SnpEff `ANN` (and, potentially, a pluggable annotation-format
registry) so gene edges can be derived from VCFs annotated by tools other than
VEP. Each format needs its own header-format discovery and gene-field extraction.
