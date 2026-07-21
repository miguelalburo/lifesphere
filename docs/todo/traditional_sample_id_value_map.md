# Traditional ingest — sample-id value-map sidecar for header/metadata mismatch

Deferred from the traditional-format ingest epic (#44).

## Scope cut

v1 requires the matrix sample-axis ids (and VCF sample columns) to **exact-match**
the `Sample` set from the metadata table. Reconciliation reports any unmatched id
as a loud `! skip` and drops it — but there is no way to *repair* a genuine,
systematic naming mismatch (e.g. matrix `Tumor_01` vs metadata `TUMOR-01`).

## Follow-on

Add an optional sample-id value-map sidecar (matrix/VCF id → metadata id) applied
during reconciliation, so a known header/metadata mismatch can be corrected with
config rather than by hand-editing the source matrix. Keep the loud-skip default
for ids not covered by the map.
