# Traditional ingest — in-pipeline VCF left-alignment via bcftools

Deferred from the traditional-format ingest epic (#44).

## Scope cut

v1 requires the input VCF to be **pre-normalized** (left-aligned upstream with
`bcftools norm`). The reader itself performs only a pure-Python defensive
multi-allelic split and takes **no** dependency on bcftools or a reference FASTA,
keeping the pipeline dependency-light.

## Follow-on

Optionally own VCF left-alignment / normalization in-pipeline (e.g. shelling out
to bcftools when available, or a pure-Python equivalent). This trades the
dependency-light guarantee for accepting un-normalized VCFs directly, so it needs
a deliberate decision on the dependency and a reference-genome source.
