"""Ontology standardisation lookup for the Stage 1 standardisation pipeline.

Reads ``config/schemas/standardisation.json`` (declaring which properties on which
node labels are "key" and which crosswalk/vocabulary each resolves against) and the
corresponding offline crosswalk CSVs in ``config/crosswalks/``. Called per-row from
``standardise_node`` in ``run.py`` to append a provenance column family for each
declared key property.

Per-row ordering (as invoked from run.py): placeholder-scrub → alias → lookup.
List-valued columns (stringified Python lists) are split and each element is looked
up individually; the result is rejoined as a pipe-separated string.

Provenance column family per declared property (snake; _camel in run.py renders
them camelCase at output):

    {col}_ontology_id           always (empty when unmapped / not_applicable)
    {col}_source_vocabulary     always
    {col}_ontology_mapping_status  always
    {col}_source_value          always (raw input preserved)
    {col}_config_key            always  ("{Label}.{col}")
    {col}_confidence_score      only when confidence_score: true in config

ontologyMappingStatus enum:
    exact_match | synonym_match | fuzzy_match | source_provided |
    curated | unmapped | not_applicable
"""

import ast
import csv
import json
from pathlib import Path
from typing import NamedTuple


class _CrosswalkRow(NamedTuple):
    ontology_id: str
    match_type: str
    confidence_score: str


class StandardisationLookup:
    """Loads and applies the standardisation config once; then called per node row."""

    def __init__(self, schema_dir: Path):
        self._schema_dir = Path(schema_dir)
        # {label: {col: config_entry}}
        self._config: dict[str, dict[str, dict]] = {}
        # {crosswalk_path_str: {normalised_source_term: _CrosswalkRow}}
        self._tables: dict[str, dict[str, _CrosswalkRow]] = {}
        self._loaded = False

    def load(self) -> None:
        std_path = self._schema_dir / "standardisation.json"
        if not std_path.exists():
            self._loaded = True
            return
        with open(std_path) as f:
            raw = json.load(f)
        self._config = raw

        # Pre-load all referenced crosswalk tables
        for label_cfg in raw.values():
            for col_cfg in label_cfg.values():
                cw_path = col_cfg.get("crosswalk")
                if cw_path and cw_path not in self._tables:
                    self._tables[cw_path] = self._load_crosswalk(Path(cw_path))
        self._loaded = True

    def _load_crosswalk(self, path: Path) -> dict[str, _CrosswalkRow]:
        table: dict[str, _CrosswalkRow] = {}
        if not path.exists():
            return table
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                term = (row.get("source_term") or "").strip().lower()
                if not term:
                    continue
                table[term] = _CrosswalkRow(
                    ontology_id=row.get("ontology_id", ""),
                    match_type=row.get("match_type", "exact_match"),
                    confidence_score=row.get("confidence_score", ""),
                )
        return table

    def labels(self) -> set[str]:
        return set(self._config.keys())

    def extra_columns(self, label: str) -> list[str]:
        """Return the additional snake_case provenance column names for this label."""
        cols: list[str] = []
        for col, cfg in self._config.get(label, {}).items():
            cols.extend([
                f"{col}_ontology_id",
                f"{col}_source_vocabulary",
                f"{col}_ontology_mapping_status",
                f"{col}_source_value",
                f"{col}_config_key",
            ])
            if cfg.get("confidence_score"):
                cols.append(f"{col}_confidence_score")
        return cols

    def apply_row(self, label: str, raw_row: dict, clean_val: callable) -> list[str]:
        """Return provenance values in the same order as extra_columns(label)."""
        values: list[str] = []
        for col, cfg in self._config.get(label, {}).items():
            raw = clean_val(raw_row.get(col, ""))
            result = self._lookup_value(label, col, raw, cfg)
            values.extend([
                result["ontology_id"],
                result["source_vocabulary"],
                result["ontology_mapping_status"],
                result["source_value"],
                result["config_key"],
            ])
            if cfg.get("confidence_score"):
                values.append(result.get("confidence_score", ""))
        return values

    def _lookup_value(self, label: str, col: str, raw: str, cfg: dict) -> dict:
        config_key = f"{label}.{col}"
        vocabulary = cfg.get("vocabulary", "")
        base: dict = {
            "ontology_id": "",
            "source_vocabulary": vocabulary,
            "source_value": raw,
            "config_key": config_key,
            "confidence_score": "",
        }

        if cfg.get("source_provided"):
            base["ontology_mapping_status"] = "source_provided" if raw else "unmapped"
            return base

        cw_path = cfg.get("crosswalk")
        if not cw_path:
            base["ontology_mapping_status"] = "not_applicable"
            return base

        table = self._tables.get(cw_path, {})
        if not raw:
            base["ontology_mapping_status"] = "unmapped"
            return base

        # List-valued: try to split a stringified Python list
        elements = _split_list(raw)
        if len(elements) > 1:
            return self._lookup_list(elements, vocabulary, cw_path, config_key, table, cfg)

        hit = table.get(raw.strip().lower())
        if hit:
            base["ontology_id"] = hit.ontology_id
            base["ontology_mapping_status"] = hit.match_type
            if cfg.get("confidence_score") and hit.confidence_score:
                base["confidence_score"] = hit.confidence_score
        else:
            base["ontology_mapping_status"] = "unmapped"
        return base

    def _lookup_list(self, elements: list[str], vocabulary: str, cw_path: str,
                     config_key: str, table: dict, cfg: dict) -> dict:
        ids, statuses, scores = [], [], []
        for elem in elements:
            hit = table.get(elem.strip().lower())
            if hit:
                ids.append(hit.ontology_id)
                statuses.append(hit.match_type)
                if cfg.get("confidence_score") and hit.confidence_score:
                    scores.append(hit.confidence_score)
            else:
                ids.append("")
                statuses.append("unmapped")
        overall_status = "unmapped" if all(s == "unmapped" for s in statuses) else statuses[0]
        return {
            "ontology_id": "|".join(ids),
            "source_vocabulary": vocabulary,
            "ontology_mapping_status": overall_status,
            "source_value": "|".join(elements),
            "config_key": config_key,
            "confidence_score": "|".join(scores) if scores else "",
        }


def _split_list(value: str) -> list[str]:
    """Split a stringified Python list if detected; else return single-element list."""
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            parsed = ast.literal_eval(stripped)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (ValueError, SyntaxError):
            pass
    return [value]


def load(schema_dir: Path) -> StandardisationLookup:
    """Convenience: construct and load a StandardisationLookup in one call."""
    lookup = StandardisationLookup(schema_dir)
    lookup.load()
    return lookup
