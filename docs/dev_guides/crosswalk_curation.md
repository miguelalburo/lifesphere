# Crosswalk curation

Crosswalk CSVs live in `config/crosswalks/`. Each file maps raw GDC term values
to an external ontology identifier with a provenance `match_type`.

## File format

```
source_term,ontology_id,match_type,confidence_score
Breast,C50.9,exact_match,
Paclitaxel,rxcui:56946,exact_match,
```

`match_type` values: `exact_match` | `synonym_match` | `fuzzy_match`.  
`confidence_score` is optional (leave blank when not set by the curation tool).

The standardise engine reads these at runtime via `src/standardise/lookup.py`.
Missing rows surface as `ontologyMappingStatus = unmapped` in the node CSVs — not
a pipeline error.

## How crosswalks are populated today

The initial TCGA population was done **in-session** (manually curated by Claude
during the July 2026 extraction session). Coverage is good for common TCGA terms
but sparse for experimental drugs and rare diagnoses.

## Recommended future approach: free public API script

Build `scripts/populate_crosswalks_api.py` that replaces the Anthropic-API version
(`scripts/populate_crosswalks.py`). The following endpoints are free and require no
API key:

| Vocabulary | Endpoint | Notes |
|------------|----------|-------|
| NCIt, ICD-O-3, WHO Grade | [EBI OLS4](https://www.ebi.ac.uk/ols4/api) | `GET /search?q=<term>&ontology=ncit` |
| RxNorm | [NLM RxNav](https://rxnav.nlm.nih.gov/REST/rxcui.json?name=<term>) | Returns RxCUI; use `allsrc=1` for broader coverage |
| HGNC | [HGNC REST](https://rest.genenames.org/search/<symbol>) | Returns HGNC ID and approved symbol |
| LOINC | [LOINC FHIR](https://fhir.loinc.org/CodeSystem/$lookup?system=http://loinc.org&code=<loinc>) | Needs free registration for full access |
| NCBI Taxonomy | [NCBI E-utilities](https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=taxonomy&term=<term>) | No key needed for low-volume use |
| UniProt | [UniProt REST](https://rest.uniprot.org/uniprotkb/search?query=<term>&fields=accession) | No key needed |

### Suggested script design

1. Reuse `collect_terms()` from `populate_crosswalks.py` (unchanged).
2. Replace `map_terms()` with per-vocabulary API handlers, one function each.
3. Rate-limit with `time.sleep(0.2)` between calls to stay within free-tier limits.
4. Write results with the same `write_crosswalk()` function.

This makes curation repeatable when a new dataset arrives and removes the Anthropic
billing dependency entirely.
