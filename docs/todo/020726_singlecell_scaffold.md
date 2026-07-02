# TODO — Single-cell / spatial reshaper scaffold (2026-07-02)

Schema is in place (entities.json / edges.json / schema_config.yaml, audit green),
now realigned to the `neo4j_updated_schema_draft_3.md` design (CellSet + provenance).
The layer is inert until a reshaper emits its TSVs.

- [ ] `src/extract/singlecell_reshape.py` (mirror `omics_reshape.py`): read `.h5ad`,
      upload matrix to external store, emit a `processed_output` row (`output_id`,
      checksum, format, path) and put `output_id` on the Assay row.
- [ ] Dissociated scRNA → **CellSet**, NOT per-cell nodes. Emit `cell_set`,
      edge-only `cell_set_membership` (CONTRIBUTES_TO props: contributed_cell_count,
      fraction_of_sample_cells), `cell_state`. Annotation provenance rides on
      ANNOTATED_AS_CELL_TYPE (props: source_value, ontology_mapping_status).
- [ ] Spatial → keep per-unit `cell` (x,y) + `adjacency` (ADJACENT_TO) + `tissue_region`.
- [ ] Also emit `pseudobulk`, `cell_type` (CL), and `observation_output` (obs_id,
      output_id) for FROM_OUTPUT.
- [ ] `disease` reference + `disease_id` FK on diagnosis (extractor maps
      primary_diagnosis → MONDO/NCIt) to activate OF_DISEASE.
- [ ] IDs: `cell_set_id`, `cell_id = {assay_id}:{barcode}`, `pseudobulk_id` per schema.
- [ ] Add `aliases.json` entries (barcode/cell_id, leiden/seurat_clusters→cell_set).
- [ ] Unit tests + reshape→standardise→validate integration (mirror
      `tests/test_omics_reshape.py`); then run schema-verify.

Done in this pass: edge-property support in `standardise_edge` (P1 enabler);
CellSet/CellState/Disease/ProcessedDataOutput schema. Caveat: MARKER_GENE score &
ADJACENT_TO distance still not carried (reify if needed). Settle external-matrix
store before building. See `docs/todo/020726_roadmap.md` and
`docs/other/neo4j_updated_schema_draft_3.md`.
