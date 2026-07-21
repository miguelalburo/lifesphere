# Traditional ingest — per-sample assay provenance from a metadata column

Deferred from the traditional-format ingest epic (#44).

## Scope cut

v1 declares **one assay per matrix** via the `assay:` sub-block in the reshape
spec: its provenance (platform, library strategy, reference genome, annotation
version) is stamped as constant columns on every observation the matrix produces,
and dedups to one `Assay` node / one `ASSAYED_BY` edge per sample. There is no way
to vary the assay per sample within a single matrix.

## Follow-on

Add support for deriving per-sample assay provenance from a metadata column, so a
matrix whose samples were assayed on different platforms/kits can carry distinct
`Assay` nodes. Needs a way to reference the metadata assay column from the reshape
spec and join it onto each observation during the melt.
