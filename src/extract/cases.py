import csv
import json
from pathlib import Path

from . import gdc_api

_DATA_DICT: dict[str, list[str]] = json.loads(
    (Path(__file__).parent / "gdc_data_dict.json").read_text()
)

# Maps each entity in gdc_data_dict.json to its dot-notation prefix on the /cases API.
_ENTITY_PREFIX: dict[str, str] = {
    "demographic":              "demographic",
    "diagnosis":                "diagnoses",
    "exposure":                 "exposures",
    "family_history":           "family_histories",
    "follow_up":                "follow_ups",
    "treatment":                "diagnoses.treatments",
    "pathology_detail":         "diagnoses.pathology_details",
    "other_clinical_attribute": "other_clinical_attributes",
}

# Molecular test fields are defined here rather than in gdc_data_dict.json because
# molecular_test nests under both diagnoses and follow_ups; it needs special multi-source
# collection rather than the single-path _resolve() used for other entities.
_MOLECULAR_TEST_FIELDS: list[str] = [
    "gene_symbol", "molecular_analysis_method", "test_result",
    "aa_change", "aneuploidy", "antigen", "biospecimen_type", "biospecimen_volume",
    "blood_test_normal_range_lower", "blood_test_normal_range_upper", "cell_count",
    "chromosomal_translocation", "chromosome", "chromosome_arm", "clonality",
    "copy_number", "cytoband", "days_to_test", "exon", "histone_family",
    "histone_variant", "hpv_strain", "intron", "laboratory_test",
    "loci_abnormal_count", "loci_count", "locus", "mismatch_repair_mutation",
    "mitotic_count", "mitotic_total_area", "molecular_consequence", "mutation_codon",
    "pathogenicity", "ploidy", "second_exon", "second_gene_symbol",
    "specialized_molecular_test", "staining_intensity_scale", "staining_intensity_value",
    "test_analyte_type", "test_units", "test_value", "test_value_range",
    "timepoint_category", "transcript", "variant_origin", "variant_type", "zygosity",
]

_BASE_FIELDS: list[str] = [
    "case_id", "submitter_id",
    "disease_type", "primary_site",
    "index_date", "index_date_type",
    "project.project_id", "project.name", "project.program.name",
]

FIELDS: list[str] = list(_BASE_FIELDS)
for _entity, _prefix in _ENTITY_PREFIX.items():
    for _field in _DATA_DICT.get(_entity, []):
        FIELDS.append(f"{_prefix}.{_field}")
FIELDS += [
    "samples.sample_id", "samples.submitter_id", "samples.sample_type",
    "samples.tissue_type", "samples.tumor_descriptor",
    "samples.days_to_collection", "samples.days_to_sample_procurement",
    "samples.portions.analytes.aliquots.aliquot_id",
    "samples.portions.analytes.aliquots.submitter_id",
    "files.file_id", "files.file_name", "files.data_type",
    "files.data_category", "files.access",
]
for _field in _MOLECULAR_TEST_FIELDS:
    FIELDS.append(f"diagnoses.molecular_tests.{_field}")
    FIELDS.append(f"follow_ups.molecular_tests.{_field}")


def _resolve(c: dict, prefix: str) -> dict:
    """Navigate a dot-notation prefix, taking list[0] at each array step."""
    obj = c
    for part in prefix.split("."):
        val = obj.get(part)
        if not val:
            return {}
        obj = val[0] if isinstance(val, list) else val
        if not isinstance(obj, dict):
            return {}
    return obj


def _collect_molecular_tests(c: dict) -> list[dict]:
    """Gather all molecular_test dicts from diagnoses and follow_ups."""
    tests: list[dict] = []
    for diag in (c.get("diagnoses") or []):
        tests.extend(diag.get("molecular_tests") or [])
    for fu in (c.get("follow_ups") or []):
        tests.extend(fu.get("molecular_tests") or [])
    return tests


def flatten(c: dict) -> dict:
    proj = c.get("project") or {}
    row: dict = {
        "case_id":         c.get("case_id", ""),
        "submitter_id":    c.get("submitter_id", ""),
        "disease_type":    c.get("disease_type", ""),
        "primary_site":    c.get("primary_site", ""),
        "index_date":      c.get("index_date", ""),
        "index_date_type": c.get("index_date_type", ""),
        "project_id":      proj.get("project_id", ""),
        "project_name":    proj.get("name", ""),
        "program_name":    (proj.get("program") or {}).get("name", ""),
    }

    for entity, prefix in _ENTITY_PREFIX.items():
        obj = _resolve(c, prefix)
        for field in _DATA_DICT.get(entity, []):
            row[f"{entity}_{field}"] = obj.get(field, "")

    samples = c.get("samples") or []
    row["sample_types"] = "; ".join(
        sorted({s.get("sample_type", "") for s in samples if s.get("sample_type")})
    )
    row["num_samples"] = len(samples)

    aliquot_ids, aliquot_sids = [], []
    for sample in samples:
        for portion in (sample.get("portions") or []):
            for analyte in (portion.get("analytes") or []):
                for aliquot in (analyte.get("aliquots") or []):
                    if aid := aliquot.get("aliquot_id"):
                        aliquot_ids.append(aid)
                    if sid := aliquot.get("submitter_id"):
                        aliquot_sids.append(sid)
    row["aliquot_ids"]           = "; ".join(aliquot_ids)
    row["aliquot_submitter_ids"] = "; ".join(aliquot_sids)

    files = c.get("files") or []
    row["file_ids"]             = "; ".join(f.get("file_id", "")       for f in files if f.get("file_id"))
    row["file_data_types"]      = "; ".join(sorted({f.get("data_type", "")      for f in files if f.get("data_type")}))
    row["file_data_categories"] = "; ".join(sorted({f.get("data_category", "")  for f in files if f.get("data_category")}))
    row["file_access"]          = "; ".join(sorted({f.get("access", "")         for f in files if f.get("access")}))

    mol_tests = _collect_molecular_tests(c)
    for field in _MOLECULAR_TEST_FIELDS:
        vals = [str(t[field]) for t in mol_tests if t.get(field) not in (None, "")]
        row[f"molecular_test_{field}"] = "; ".join(vals)

    return row


def _fetch(filters: dict) -> list[dict]:
    hits, from_pos, total = [], 0, None
    while total is None or from_pos < total:
        payload = {"filters": filters, "fields": ",".join(FIELDS), "size": 500, "from": from_pos}
        d = gdc_api.post(gdc_api.CASES_URL, payload)["data"]
        if total is None:
            total = d["pagination"]["total"]
            print(f"  Total cases: {total}")
        hits.extend(d["hits"])
        from_pos += len(d["hits"])
        print(f"  Fetched {from_pos}/{total}...", flush=True)
    return hits


def fetch_all(project_id: str) -> list[dict]:
    return _fetch({"op": "=", "content": {"field": "project.project_id", "value": project_id}})


def fetch_by_program(program: str) -> list[dict]:
    return _fetch({"op": "=", "content": {"field": "project.program.name", "value": program}})


def fetch_by_ids(case_ids: list[str]) -> list[dict]:
    return _fetch({"op": "in", "content": {"field": "case_id", "value": case_ids}})


def _write_tsv(rows: list[dict], out_path: Path) -> None:
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved {len(rows)} cases × {len(rows[0])} columns → {out_path}")


def download_cases_tsv(project_id: str, out_dir: Path) -> None:
    print("\n[2/2] Fetching harmonized cases from GDC /cases endpoint...")
    hits = fetch_all(project_id)
    if not hits:
        print("  No cases found.")
        return
    _write_tsv([flatten(c) for c in hits], out_dir / f"{project_id}.metadata.tsv")


def download_cases_tsv_by_program(program: str, out_dir: Path) -> None:
    print("\n[1/1] Fetching harmonized cases from GDC /cases endpoint...")
    hits = fetch_by_program(program)
    if not hits:
        print("  No cases found.")
        return
    _write_tsv([flatten(c) for c in hits], out_dir / f"{program}.metadata.tsv")


def download_cases_tsv_by_ids(case_ids: list[str], out_dir: Path) -> None:
    print("\n[1/1] Fetching harmonized cases from GDC /cases endpoint...")
    hits = fetch_by_ids(case_ids)
    if not hits:
        print("  No cases found.")
        return
    _write_tsv([flatten(c) for c in hits], out_dir / "cases.metadata.tsv")
