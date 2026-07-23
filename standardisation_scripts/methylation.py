#!/usr/bin/env python3

import argparse
import csv
import glob
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from transform_library import TEMPLATES


# -----------------------------------------------------------------------------
# Schema contract required by this methylation standardisation script
# -----------------------------------------------------------------------------

REQUIRED_NODE_PRIMARY_KEYS = {
    "CpGSite": "cpgId",
    "MethylationObservation": "methylationObservationId",
    "MethylationStatusRule": "methylationStatusRuleId",
    "Sample": "sampleId",
    "Assay": "assayId",
}

REQUIRED_RELATIONSHIP_PATTERNS = {
    "HAS_METHYLATION_OBSERVATION": (
        "Sample",
        "MethylationObservation",
    ),
    "MEASURES_CPG": (
        "MethylationObservation",
        "CpGSite",
    ),
    "CLASSIFIED_USING": (
        "MethylationObservation",
        "MethylationStatusRule",
    ),
}

# These are not all Neo4j-required fields. They are the minimum fields needed
# for this script to create meaningful, linkable methylation observations.
REQUIRED_CPG_OUTPUT_FIELDS = [
    "cpgId",
]

REQUIRED_OBSERVATION_OUTPUT_FIELDS = [
    "methylationObservationId",
    "observationType",
    "sampleId",
    "cpgId",
    "betaValue",
    "sourceDataset",
]

REQUIRED_RULE_EXECUTION_FIELDS = [
    "methylationStatusRuleId",
    "ruleName",
    "ruleType",
    "ruleDescription",
    "betaValueScale",
    "hypoThreshold",
    "hyperThreshold",
    "intermediateLowerBound",
    "intermediateUpperBound",
]


# -----------------------------------------------------------------------------
# Basic utilities
# -----------------------------------------------------------------------------


def import_transform_templates():
    """Import the local transformation templates."""
    return TEMPLATES


def load_json(path, description):
    path = Path(path).expanduser()

    if not path.is_file():
        raise FileNotFoundError(f"{description} was not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"{description} must contain a top-level JSON object.")

    return data


def series_is_blank(series):
    text = series.astype("string").str.strip()
    return bool((text.isna() | text.eq("")).all())


def remove_stale_temp_file(path):
    path = Path(path)
    if path.exists():
        path.unlink()


def write_csv_atomically(dataframe, final_path):
    final_path = Path(final_path)
    temp_path = Path(str(final_path) + ".tmp")

    remove_stale_temp_file(temp_path)
    dataframe.to_csv(temp_path, index=False)
    os.replace(temp_path, final_path)


def append_csv_chunk(dataframe, temp_path, first_chunk):
    dataframe.to_csv(
        temp_path,
        mode="w" if first_chunk else "a",
        header=first_chunk,
        index=False,
    )


def read_identifier_file(path):
    """
    Read identifiers from a one-column TXT/CSV/TSV file.

    A header is tolerated. Blank values are ignored.
    """
    if path is None:
        return None

    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Identifier list was not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            reader = csv.reader(handle, dialect)
        except csv.Error:
            reader = csv.reader(handle)

        values = []
        for row in reader:
            if not row:
                continue
            value = str(row[0]).strip()
            if value:
                values.append(value)

    if not values:
        raise ValueError(f"Identifier list is empty: {path}")

    common_headers = {
        "id",
        "sampleid",
        "sample_id",
        "cpgid",
        "cpg_id",
    }
    if values[0].lower() in common_headers:
        values = values[1:]

    if not values:
        raise ValueError(f"Identifier list contains only a header: {path}")

    return set(values)


# -----------------------------------------------------------------------------
# Schema loading and validation
# -----------------------------------------------------------------------------


def build_schema_maps(schema):
    nodes = schema.get("nodes")
    relationships = schema.get("relationships")

    if not isinstance(nodes, list):
        raise ValueError("Schema JSON must contain a 'nodes' list.")
    if not isinstance(relationships, list):
        raise ValueError("Schema JSON must contain a 'relationships' list.")

    node_map = {}
    for node in nodes:
        label = node.get("label")
        if not label:
            raise ValueError("A schema node is missing its label.")
        if label in node_map:
            raise ValueError(f"Duplicate node definition in schema: {label}")
        node_map[label] = node

    relationship_map = {}
    for relationship in relationships:
        rel_type = relationship.get("type")
        if not rel_type:
            raise ValueError("A schema relationship is missing its type.")
        relationship_map.setdefault(rel_type, []).append(relationship)

    return node_map, relationship_map


def node_property_names(node_definition):
    properties = node_definition.get("properties", [])
    return [prop["name"] for prop in properties]


def node_property_types(node_definition):
    return {
        prop["name"]: prop.get("dataType", "String")
        for prop in node_definition.get("properties", [])
    }


def validate_schema_contract(schema):
    """Fail early if the supplied schema no longer matches this workflow."""
    node_map, relationship_map = build_schema_maps(schema)

    for label, expected_primary_key in REQUIRED_NODE_PRIMARY_KEYS.items():
        if label not in node_map:
            raise ValueError(f"Required schema node is missing: {label}")

        actual_primary_key = node_map[label].get("primaryKey")
        if actual_primary_key != expected_primary_key:
            raise ValueError(
                f"Schema primary key mismatch for {label}: expected "
                f"'{expected_primary_key}', found '{actual_primary_key}'."
            )

        property_names = node_property_names(node_map[label])
        if expected_primary_key not in property_names:
            raise ValueError(
                f"Primary key '{expected_primary_key}' is absent from the "
                f"{label} property catalogue."
            )

    for rel_type, (expected_source, expected_target) in (
        REQUIRED_RELATIONSHIP_PATTERNS.items()
    ):
        candidates = relationship_map.get(rel_type, [])
        matching = [
            rel
            for rel in candidates
            if rel.get("source") == expected_source
            and rel.get("target") == expected_target
        ]
        if not matching:
            raise ValueError(
                f"Required relationship pattern is missing: "
                f"(:{expected_source})-[:{rel_type}]->(:{expected_target})"
            )

    required_observation_properties = {
        "methylationObservationId",
        "observationType",
        "sampleId",
        "assayId",
        "cpgId",
        "betaValue",
        "methylationStatus",
        "methylationStatusMethod",
        "numCpGSites",
        "modificationType",
        "qualityScore",
        "normalizationMethod",
        "sourceDataset",
        "sourceFile",
        "pipelineVersion",
        "configKey",
    }

    actual_observation_properties = set(
        node_property_names(node_map["MethylationObservation"])
    )

    missing = required_observation_properties - actual_observation_properties
    if missing:
        raise ValueError(
            "The supplied schema is missing MethylationObservation "
            f"properties required by this workflow: {sorted(missing)}"
        )

    return node_map, relationship_map


# -----------------------------------------------------------------------------
# Type coercion according to the schema JSON
# -----------------------------------------------------------------------------


def coerce_boolean_series(series, field_name, context):
    if pd.api.types.is_bool_dtype(series):
        return series.astype("boolean")

    text = series.astype("string").str.strip().str.lower()
    true_values = {"true", "1", "yes", "y"}
    false_values = {"false", "0", "no", "n"}
    blank_mask = text.isna() | text.eq("")
    invalid_mask = ~(text.isin(true_values | false_values) | blank_mask)

    if invalid_mask.any():
        examples = text.loc[invalid_mask].drop_duplicates().head(10).tolist()
        raise ValueError(
            f"{context}.{field_name} contains invalid Boolean values: {examples}"
        )

    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    result.loc[text.isin(true_values)] = True
    result.loc[text.isin(false_values)] = False
    return result


def coerce_dataframe_to_schema(dataframe, node_definition, context):
    """Coerce supported scalar types while preserving blank optional values."""
    property_types = node_property_types(node_definition)
    output = dataframe.copy()

    for field_name, data_type in property_types.items():
        if field_name not in output.columns:
            continue

        normalized_type = data_type.lower().strip()

        if normalized_type == "integer":
            raw = output[field_name]
            numeric = pd.to_numeric(raw, errors="coerce")
            nonblank = raw.astype("string").str.strip().ne("") & raw.notna()
            invalid = nonblank & numeric.isna()
            if invalid.any():
                examples = raw.loc[invalid].drop_duplicates().head(10).tolist()
                raise ValueError(
                    f"{context}.{field_name} contains non-integer values: "
                    f"{examples}"
                )
            fractional = numeric.notna() & (numeric % 1 != 0)
            if fractional.any():
                examples = raw.loc[fractional].drop_duplicates().head(10).tolist()
                raise ValueError(
                    f"{context}.{field_name} contains fractional values but the "
                    f"schema requires Integer: {examples}"
                )
            output[field_name] = numeric.astype("Int64")

        elif normalized_type == "float":
            raw = output[field_name]
            numeric = pd.to_numeric(raw, errors="coerce")
            nonblank = raw.astype("string").str.strip().ne("") & raw.notna()
            invalid = nonblank & numeric.isna()
            if invalid.any():
                examples = raw.loc[invalid].drop_duplicates().head(10).tolist()
                raise ValueError(
                    f"{context}.{field_name} contains non-numeric values: "
                    f"{examples}"
                )
            output[field_name] = numeric.astype("Float64")

        elif normalized_type == "boolean":
            output[field_name] = coerce_boolean_series(
                output[field_name],
                field_name,
                context,
            )

        elif normalized_type.startswith("string"):
            output[field_name] = output[field_name].astype("string")

    return output


# -----------------------------------------------------------------------------
# LifeSphere transform helpers
# -----------------------------------------------------------------------------


def normalise_transform_result(result, column_name, index):
    if isinstance(result, pd.Series):
        return result.reindex(index)

    if isinstance(result, pd.DataFrame):
        if column_name in result.columns:
            return result[column_name].reindex(index)
        if result.shape[1] == 1:
            return result.iloc[:, 0].reindex(index)
        raise ValueError(
            f"Transform for '{column_name}' returned multiple columns without "
            "a matching output column."
        )

    return pd.Series(result, index=index)


def apply_transform(
    dataframe,
    column_name,
    transform_name,
    templates,
    configured_params=None,
):
    if transform_name not in templates:
        raise KeyError(
            f"Transform '{transform_name}' is not available in "
            "transform_library.TEMPLATES."
        )

    temporary = dataframe[[column_name]].copy()

    default_params = {}
    if transform_name == "strip_chr_prefix":
        default_params = {"case_insensitive": True}
    elif transform_name == "clamp_0_1":
        default_params = {"invalid_to": ""}
    elif transform_name in {"to_int", "to_float"}:
        default_params = {"invalid_to": ""}

    params = dict(default_params)
    if configured_params:
        params.update(configured_params)

    result = templates[transform_name](
        temporary,
        [column_name],
        params,
    )

    return normalise_transform_result(result, column_name, dataframe.index)


# -----------------------------------------------------------------------------
# Methylation status rule handling
# -----------------------------------------------------------------------------


def observation_mapping_uses_status_derivation(observation_config):
    return any(
        rules.get("mode") == "compute"
        and rules.get("recipe") == "derive_methylation_status"
        for rules in observation_config.values()
    )


def load_status_rule(config, rule_node_definition, classification_requested):
    """
    Load the classification rule from mappings.MethylationStatusRule.

    The JSON stores MethylationStatusRule as a node mapping, alongside
    CpGSite and MethylationObservation. Each property is therefore resolved
    from its mapping instruction before it is used as a runtime value.
    """
    mappings = config.get("mappings")

    if not isinstance(mappings, dict):
        raise ValueError(
            "The mapping JSON must contain a top-level 'mappings' object."
        )

    rule_mapping = mappings.get("MethylationStatusRule")

    if not classification_requested:
        if rule_mapping is not None:
            print(
                "A mappings.MethylationStatusRule configuration is present, "
                "but MethylationObservation.methylationStatus is not "
                "configured with recipe='derive_methylation_status'. "
                "The rule will not be used."
            )
        return None, None

    if not isinstance(rule_mapping, dict):
        raise ValueError(
            "The mapping requests derive_methylation_status, but the JSON "
            "lacks mappings.MethylationStatusRule."
        )

    # Resolve node-mapping instructions such as:
    # "hypoThreshold": {"mode": "default", "value": "0.3"}
    # into runtime values such as:
    # "hypoThreshold": "0.3"
    raw_rule = {}

    for field_name, rules in rule_mapping.items():
        if not isinstance(rules, dict):
            raise ValueError(
                f"MethylationStatusRule.{field_name} must be a mapping object."
            )

        mode = rules.get("mode")

        if mode != "default":
            raise ValueError(
                f"MethylationStatusRule.{field_name} currently supports only "
                "mode='default'."
            )

        raw_rule[field_name] = rules.get("value", "")

    missing = [
        field
        for field in REQUIRED_RULE_EXECUTION_FIELDS
        if field not in raw_rule or str(raw_rule[field]).strip() == ""
    ]
    if missing:
        raise ValueError(
            "mappings.MethylationStatusRule is missing required fields: "
            f"{missing}"
        )

    try:
        hypo_threshold = float(raw_rule["hypoThreshold"])
        hyper_threshold = float(raw_rule["hyperThreshold"])
        intermediate_lower = float(raw_rule["intermediateLowerBound"])
        intermediate_upper = float(raw_rule["intermediateUpperBound"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Methylation rule threshold values must be numerically parseable."
        ) from exc

    if not (0.0 <= hypo_threshold < hyper_threshold <= 1.0):
        raise ValueError(
            "Methylation thresholds must satisfy "
            "0 <= hypoThreshold < hyperThreshold <= 1."
        )

    if intermediate_lower != hypo_threshold:
        raise ValueError(
            "For the three-state absolute-threshold rule, "
            "intermediateLowerBound must equal hypoThreshold."
        )

    if intermediate_upper != hyper_threshold:
        raise ValueError(
            "For the three-state absolute-threshold rule, "
            "intermediateUpperBound must equal hyperThreshold."
        )

    # The active schema does not currently define separate boundary-operator
    # properties. The current configured ruleDescription explicitly defines
    # the outer thresholds as inclusive: beta <= hypoThreshold and
    # beta >= hyperThreshold. The middle class is therefore the remaining
    # interval between the two thresholds.
    execution_rule = {
        "hypoThreshold": hypo_threshold,
        "hyperThreshold": hyper_threshold,
        "hypoInclusive": True,
        "hyperInclusive": True,
        "hypoLabel": "Hypomethylated",
        "intermediateLabel": "Intermediate",
        "hyperLabel": "Hypermethylated",
        "ruleType": str(raw_rule["ruleType"]),
        "configKey": str(raw_rule.get("configKey", "")),
    }

    rule_columns = node_property_names(rule_node_definition)
    rule_row = {
        column: raw_rule.get(column, "")
        for column in rule_columns
    }

    rule_dataframe = pd.DataFrame([rule_row], columns=rule_columns)
    rule_dataframe = coerce_dataframe_to_schema(
        rule_dataframe,
        rule_node_definition,
        "MethylationStatusRule",
    )

    validate_required_fields(
        rule_dataframe,
        ["methylationStatusRuleId"],
        "MethylationStatusRule",
    )

    execution_rule["methylationStatusRuleId"] = str(
        rule_dataframe.loc[0, "methylationStatusRuleId"]
    )

    return execution_rule, rule_dataframe

def derive_methylation_status(beta_series, execution_rule):
    beta = pd.to_numeric(beta_series, errors="coerce")

    status = pd.Series("", index=beta.index, dtype="string")

    if execution_rule["hypoInclusive"]:
        hypo_mask = beta <= execution_rule["hypoThreshold"]
    else:
        hypo_mask = beta < execution_rule["hypoThreshold"]

    if execution_rule["hyperInclusive"]:
        hyper_mask = beta >= execution_rule["hyperThreshold"]
    else:
        hyper_mask = beta > execution_rule["hyperThreshold"]

    overlap = hypo_mask & hyper_mask
    if overlap.any():
        raise ValueError("The methylation rule creates overlapping classes.")

    intermediate_mask = beta.notna() & ~hypo_mask & ~hyper_mask

    status.loc[hypo_mask] = execution_rule["hypoLabel"]
    status.loc[intermediate_mask] = execution_rule["intermediateLabel"]
    status.loc[hyper_mask] = execution_rule["hyperLabel"]

    return status


# -----------------------------------------------------------------------------
# Output validation
# -----------------------------------------------------------------------------


def validate_required_fields(dataframe, required_fields, context):
    missing = [field for field in required_fields if field not in dataframe]
    if missing:
        raise ValueError(f"{context} output is missing fields: {missing}")

    blank = [
        field
        for field in required_fields
        if series_is_blank(dataframe[field])
    ]
    if blank:
        raise ValueError(
            f"{context} output has entirely blank required fields: {blank}"
        )


def validate_observation_id_mapping(observation_config):
    rules = observation_config.get("methylationObservationId")
    if not isinstance(rules, dict):
        raise ValueError(
            "MethylationObservation.methylationObservationId is not configured."
        )

    if rules.get("mode") != "compute" or rules.get("recipe") != "concat":
        raise ValueError(
            "methylationObservationId must use mode='compute' and "
            "recipe='concat' for this matrix workflow."
        )

    inputs = rules.get("inputs", [])
    if "sampleId" not in inputs or "cpgId" not in inputs:
        raise ValueError(
            "methylationObservationId concat inputs must include both sampleId "
            "and cpgId to remain unique per sample-CpG measurement."
        )


# -----------------------------------------------------------------------------
# Input discovery and matrix-column detection
# -----------------------------------------------------------------------------


def find_exactly_one_file(cohort_name, cohort_dir, pattern, description):
    matches = sorted(glob.glob(os.path.join(cohort_dir, pattern)))

    if not matches:
        raise FileNotFoundError(
            f"[{cohort_name}] No {description} matched '{pattern}'."
        )

    if len(matches) != 1:
        raise ValueError(
            f"[{cohort_name}] Expected one {description}, found "
            f"{len(matches)}: {matches}"
        )

    return matches[0]


def detect_matrix_columns(beta_file, cohort_name, selected_samples=None):
    header = pd.read_csv(beta_file, nrows=0)

    if len(header.columns) < 2:
        raise ValueError(
            f"[{cohort_name}] Beta matrix must contain one CpG identifier "
            "column and at least one sample column."
        )

    id_column = header.columns[0]
    candidate_columns = list(header.columns[1:])

    tcga_columns = [
        column
        for column in candidate_columns
        if str(column).strip().startswith("TCGA-")
    ]

    unexpected_columns = [
        column for column in candidate_columns if column not in tcga_columns
    ]

    if unexpected_columns:
        raise ValueError(
            f"[{cohort_name}] Non-TCGA columns occur after the first beta-matrix "
            "column and would be unsafe to melt as samples: "
            f"{unexpected_columns[:10]}"
        )

    stripped_ids = [str(column).strip() for column in tcga_columns]
    duplicate_mask = pd.Series(stripped_ids).duplicated(keep=False)
    if duplicate_mask.any():
        examples = (
            pd.Series(stripped_ids)
            .loc[duplicate_mask]
            .drop_duplicates()
            .head(10)
            .tolist()
        )
        raise ValueError(
            f"[{cohort_name}] Duplicate sample columns were detected: {examples}"
        )

    if selected_samples is not None:
        available = set(stripped_ids)
        missing_selected = selected_samples - available
        if missing_selected:
            print(
                f"[{cohort_name}] {len(missing_selected):,} requested sample IDs "
                "are absent from this cohort and will be ignored."
            )

        tcga_columns = [
            column
            for column in tcga_columns
            if str(column).strip() in selected_samples
        ]

    if not tcga_columns:
        raise ValueError(
            f"[{cohort_name}] No eligible TCGA sample columns remain after "
            "selection."
        )

    print(
        f"[{cohort_name}] Detected identifier column '{id_column}' and "
        f"{len(tcga_columns):,} selected TCGA sample columns."
    )

    return id_column, tcga_columns


# -----------------------------------------------------------------------------
# CpGSite node creation
# -----------------------------------------------------------------------------


def build_cpg_output(
    row_dataframe,
    cpg_config,
    cpg_node_definition,
    cohort_name,
    templates,
    selected_cpgs=None,
):
    output = pd.DataFrame(index=row_dataframe.index)

    for target_column, rules in cpg_config.items():
        if target_column not in node_property_names(cpg_node_definition):
            raise ValueError(
                f"[{cohort_name}] Mapping targets CpGSite.{target_column}, but "
                "that property is absent from the supplied schema."
            )

        mode = rules.get("mode")

        if mode == "default":
            output[target_column] = rules.get("value", "")
            continue

        if mode != "map":
            raise ValueError(
                f"[{cohort_name}] Unsupported CpGSite mode '{mode}' for "
                f"'{target_column}'."
            )

        source_column = rules.get("source", {}).get("column")
        if not source_column:
            raise ValueError(
                f"[{cohort_name}] No source column is configured for "
                f"CpGSite.{target_column}."
            )

        is_required = rules.get(
            "required",
            target_column in REQUIRED_CPG_OUTPUT_FIELDS,
        )

        if source_column not in row_dataframe.columns:
            if is_required:
                raise KeyError(
                    f"[{cohort_name}] Required source column '{source_column}' "
                    f"for CpGSite.{target_column} was not found."
                )

            print(
                f"[{cohort_name}] Optional source column '{source_column}' for "
                f"CpGSite.{target_column} was not found; blanks will be written."
            )
            output[target_column] = ""
        else:
            output[target_column] = row_dataframe[source_column]

        transform_name = rules.get("transform")
        if transform_name:
            output[target_column] = apply_transform(
                output,
                target_column,
                transform_name,
                templates,
                rules.get("params"),
            )

    columns = node_property_names(cpg_node_definition)
    output = output.reindex(columns=columns, fill_value="")
    output = coerce_dataframe_to_schema(
        output,
        cpg_node_definition,
        "CpGSite",
    )

    output["cpgId"] = output["cpgId"].astype("string").str.strip()

    invalid_cpg = ~output["cpgId"].str.match(r"^(cg\d+|ch\..+|rs\d+)$", na=False)
    if invalid_cpg.any():
        examples = (
            output.loc[invalid_cpg, "cpgId"]
            .drop_duplicates()
            .head(10)
            .tolist()
        )
        print(f"[{cohort_name}] WARNING: Dropping {invalid_cpg.sum()} unrecognized probes (e.g. {examples})")
        output = output[~invalid_cpg]


    if selected_cpgs is not None:
        output = output.loc[output["cpgId"].isin(selected_cpgs)].copy()
        if output.empty:
            raise ValueError(
                f"[{cohort_name}] No annotation rows match the selected CpG IDs."
            )

    duplicate_mask = output.duplicated(subset=["cpgId"], keep=False)
    if duplicate_mask.any():
        duplicate_rows = output.loc[duplicate_mask].copy()
        comparison_columns = [
            column for column in output.columns if column != "cpgId"
        ]

        normalized = duplicate_rows.copy()
        for column in comparison_columns:
            normalized[column] = (
                normalized[column]
                .astype("string")
                .fillna("")
                .str.strip()
            )

        conflicts = (
            normalized.groupby("cpgId", dropna=False)[comparison_columns]
            .nunique(dropna=False)
            .gt(1)
            .any(axis=1)
        )
        conflicting_ids = conflicts.loc[conflicts].index.tolist()

        if conflicting_ids:
            raise ValueError(
                f"[{cohort_name}] Conflicting duplicate CpG annotations were "
                f"found: {conflicting_ids[:10]}"
            )

        duplicate_count = int(
            output.duplicated(subset=["cpgId"], keep="first").sum()
        )
        print(
            f"[{cohort_name}] Removing {duplicate_count:,} exact duplicate CpG "
            "annotation rows."
        )
        output = output.drop_duplicates(subset=["cpgId"], keep="first")

    validate_required_fields(
        output,
        REQUIRED_CPG_OUTPUT_FIELDS,
        "CpGSite",
    )

    return output


# -----------------------------------------------------------------------------
# Wide-to-long cleaning and optional selection
# -----------------------------------------------------------------------------


def clean_melted_measurements(melted, cohort_name):
    melted["sampleId"] = melted["sampleId"].astype("string").str.strip()
    melted["cpgId"] = melted["cpgId"].astype("string").str.strip()

    invalid_sample = ~melted["sampleId"].str.startswith("TCGA-", na=False)
    if invalid_sample.any():
        examples = (
            melted.loc[invalid_sample, "sampleId"]
            .drop_duplicates()
            .head(10)
            .tolist()
        )
        raise ValueError(
            f"[{cohort_name}] Invalid sample IDs after melting: {examples}"
        )

    invalid_cpg = ~melted["cpgId"].str.match(r"^(cg\d+|ch\..+|rs\d+)$", na=False)
    if invalid_cpg.any():
        examples = (
            melted.loc[invalid_cpg, "cpgId"]
            .drop_duplicates()
            .head(10)
            .tolist()
        )
        print(f"[{cohort_name}] WARNING: Dropping {invalid_cpg.sum()} unrecognized probes after melting (e.g. {examples})")
        melted = melted[~invalid_cpg]

    raw = melted["betaValue"]
    raw_text = raw.astype("string").str.strip()
    numeric = pd.to_numeric(raw, errors="coerce")

    non_numeric = raw_text.notna() & raw_text.ne("") & numeric.isna()
    out_of_range = numeric.notna() & ~numeric.between(
        0.0,
        1.0,
        inclusive="both",
    )
    missing = numeric.isna() & ~non_numeric

    valid = numeric.notna() & ~out_of_range
    cleaned = melted.loc[valid].copy()
    cleaned["betaValue"] = numeric.loc[valid].astype("float64")

    counters = {
        "missing": int(missing.sum()),
        "nonNumeric": int(non_numeric.sum()),
        "outOfRange": int(out_of_range.sum()),
    }

    return cleaned, counters


# -----------------------------------------------------------------------------
# MethylationObservation mapping
# -----------------------------------------------------------------------------


def resolve_concat_part(item, melted, cohort_name, beta_file):
    if item in melted.columns:
        return melted[item].astype("string"), True

    dynamic_values = {
        "sourceDataset": cohort_name,
        "sourceFile": os.path.basename(beta_file),
    }
    if item in dynamic_values:
        return (
            pd.Series(
                dynamic_values[item],
                index=melted.index,
                dtype="string",
            ),
            True,
        )

    return (
        pd.Series(str(item), index=melted.index, dtype="string"),
        False,
    )


def apply_observation_mapping(
    melted,
    observation_config,
    observation_node_definition,
    cohort_name,
    beta_file,
    templates,
    execution_rule,
):
    output = pd.DataFrame(index=melted.index)
    schema_columns = node_property_names(observation_node_definition)

    for target_column, rules in observation_config.items():
        if target_column not in schema_columns:
            raise ValueError(
                f"[{cohort_name}] Mapping targets "
                f"MethylationObservation.{target_column}, but that property is "
                "absent from the supplied schema."
            )

        mode = rules.get("mode")

        if mode == "default":
            output[target_column] = rules.get("value", "")
            continue

        if mode == "map":
            source_column = rules.get("source", {}).get("column")
            if not source_column or source_column not in melted.columns:
                raise KeyError(
                    f"[{cohort_name}] Source column '{source_column}' for "
                    f"MethylationObservation.{target_column} is unavailable."
                )
            output[target_column] = melted[source_column]

            transform_name = rules.get("transform")
            if transform_name:
                output[target_column] = apply_transform(
                    output,
                    target_column,
                    transform_name,
                    templates,
                    rules.get("params"),
                )
            continue

        if mode != "compute":
            raise ValueError(
                f"[{cohort_name}] Unsupported MethylationObservation mode "
                f"'{mode}' for '{target_column}'."
            )

        recipe = rules.get("recipe")

        if recipe == "concat":
            inputs = rules.get("inputs", [])
            if not inputs:
                raise ValueError(
                    f"[{cohort_name}] No concat inputs configured for "
                    f"'{target_column}'."
                )

            resolved = [
                resolve_concat_part(item, melted, cohort_name, beta_file)
                for item in inputs
            ]
            parts = [part for part, _ in resolved]
            contains_literal = any(not is_field for _, is_field in resolved)

            # Backward compatibility: configurations that explicitly include
            # literal separators are concatenated exactly. Otherwise a safe
            # delimiter is inserted between fields.
            separator = "" if contains_literal else rules.get("delimiter", "|")

            result = parts[0]
            for part in parts[1:]:
                result = result.str.cat(part, sep=separator)
            output[target_column] = result

        elif recipe == "from_matrix_headers":
            output[target_column] = melted["sampleId"]

        elif recipe == "from_matrix_index":
            output[target_column] = melted["cpgId"]

        elif recipe == "from_matrix_values":
            output[target_column] = melted["betaValue"]
            transform_name = rules.get("transform")
            if transform_name:
                output[target_column] = apply_transform(
                    output,
                    target_column,
                    transform_name,
                    templates,
                    rules.get("params"),
                )

        elif recipe == "derive_methylation_status":
            if execution_rule is None:
                raise ValueError(
                    "derive_methylation_status was requested without a valid "
                    "methylationStatusRule."
                )
            beta_values = output.get("betaValue", melted["betaValue"])
            output[target_column] = derive_methylation_status(
                beta_values,
                execution_rule,
            )

        elif recipe == "cohort_name":
            output[target_column] = cohort_name

        elif recipe == "filename":
            output[target_column] = os.path.basename(beta_file)

        elif recipe == "status_rule_type":
            if execution_rule is None:
                output[target_column] = ""
            else:
                output[target_column] = execution_rule["ruleType"]

        elif recipe == "status_rule_config_key":
            if execution_rule is None:
                output[target_column] = ""
            else:
                output[target_column] = execution_rule["configKey"]

        else:
            raise ValueError(
                f"[{cohort_name}] Unsupported computation recipe '{recipe}' "
                f"for '{target_column}'."
            )

    output = output.reindex(columns=schema_columns, fill_value="")

    # Keep the mirror provenance properties aligned with the linked rule even
    # when the mapping file leaves them blank.
    if execution_rule is not None:
        if series_is_blank(output["methylationStatusMethod"]):
            output["methylationStatusMethod"] = execution_rule["ruleType"]
        if series_is_blank(output["configKey"]):
            output["configKey"] = execution_rule["configKey"]

    output = coerce_dataframe_to_schema(
        output,
        observation_node_definition,
        "MethylationObservation",
    )

    for identifier_column in [
        "methylationObservationId",
        "sampleId",
        "assayId",
        "cpgId",
    ]:
        output[identifier_column] = (
            output[identifier_column].astype("string").str.strip()
        )

    output["betaValue"] = pd.to_numeric(output["betaValue"], errors="coerce")
    if output["betaValue"].isna().any():
        raise ValueError(
            f"[{cohort_name}] Mapping produced missing/non-numeric betaValue "
            "values from already validated measurements."
        )

    invalid_range = ~output["betaValue"].between(
        0.0,
        1.0,
        inclusive="both",
    )
    if invalid_range.any():
        raise ValueError(
            f"[{cohort_name}] Mapping produced beta values outside [0, 1]."
        )

    validate_required_fields(
        output,
        REQUIRED_OBSERVATION_OUTPUT_FIELDS,
        "MethylationObservation",
    )

    duplicate_ids = output["methylationObservationId"].duplicated(keep=False)
    if duplicate_ids.any():
        examples = (
            output.loc[duplicate_ids, "methylationObservationId"]
            .drop_duplicates()
            .head(10)
            .tolist()
        )
        raise ValueError(
            f"[{cohort_name}] Duplicate observation IDs were created within a "
            f"chunk: {examples}"
        )

    has_status = output["methylationStatus"].astype("string").str.strip().ne("")
    if has_status.any() and execution_rule is None:
        raise ValueError(
            f"[{cohort_name}] methylationStatus values were produced without a "
            "MethylationStatusRule, which violates the schema."
        )

    if execution_rule is not None and (~has_status).any():
        raise ValueError(
            f"[{cohort_name}] A classification rule was applied, but some "
            "observations have blank methylationStatus values."
        )

    if output["assayId"].astype("string").str.strip().eq("").any():
        print(
            f"[{cohort_name}] Warning: some assayId mirror properties are blank. "
            "The schema permits this property to be optional, but assay "
            "provenance should be populated when available."
        )

    return output


# -----------------------------------------------------------------------------
# Relationship files required for canonical graph traversal
# -----------------------------------------------------------------------------


def build_relationship_chunks(observation_output, execution_rule):
    sample_to_observation = observation_output[
        ["sampleId", "methylationObservationId"]
    ].copy()

    observation_to_cpg = observation_output[
        ["methylationObservationId", "cpgId"]
    ].copy()

    if execution_rule is None:
        classified_using = pd.DataFrame(
            columns=[
                "methylationObservationId",
                "methylationStatusRuleId",
            ]
        )
    else:
        classified_using = observation_output[
            ["methylationObservationId"]
        ].copy()
        classified_using["methylationStatusRuleId"] = execution_rule[
            "methylationStatusRuleId"
        ]

    return sample_to_observation, observation_to_cpg, classified_using


# -----------------------------------------------------------------------------
# Cohort processing
# -----------------------------------------------------------------------------


def process_cohort(
    cohort_dir,
    base_output_dir,
    config,
    node_map,
    templates,
    chunk_size,
    selected_samples=None,
    selected_cpgs=None,
):
    cohort_name = os.path.basename(os.path.normpath(cohort_dir))
    output_dir = Path(base_output_dir) / cohort_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[{cohort_name}] Starting schema-aware methylation standardisation...")

    beta_file = find_exactly_one_file(
        cohort_name,
        cohort_dir,
        "*_beta_matrix.csv",
        "beta matrix",
    )
    rowdata_file = find_exactly_one_file(
        cohort_name,
        cohort_dir,
        "*_rowData_cpg_annotation.csv",
        "CpG annotation file",
    )

    mappings = config.get("mappings")
    if not isinstance(mappings, dict):
        raise KeyError("Mapping JSON must contain a top-level 'mappings' object.")

    cpg_config = mappings.get("CpGSite")
    observation_config = mappings.get("MethylationObservation")
    if not isinstance(cpg_config, dict):
        raise KeyError("Mapping JSON is missing mappings.CpGSite.")
    if not isinstance(observation_config, dict):
        raise KeyError("Mapping JSON is missing mappings.MethylationObservation.")

    validate_observation_id_mapping(observation_config)

    classification_requested = observation_mapping_uses_status_derivation(
        observation_config
    )
    execution_rule, rule_dataframe = load_status_rule(
        config,
        node_map["MethylationStatusRule"],
        classification_requested,
    )

    # ------------------------------------------------------------------
    # CpGSite
    # ------------------------------------------------------------------
    print(
        f"[{cohort_name}] Processing CpGSite from "
        f"{os.path.basename(rowdata_file)}..."
    )
    row_dataframe = pd.read_csv(rowdata_file, low_memory=False)
    cpg_output = build_cpg_output(
        row_dataframe,
        cpg_config,
        node_map["CpGSite"],
        cohort_name,
        templates,
        selected_cpgs,
    )

    cpg_path = output_dir / "cpg_sites.csv"
    write_csv_atomically(cpg_output, cpg_path)
    valid_cpg_ids = set(cpg_output["cpgId"].astype(str))

    print(
        f"[{cohort_name}] Saved {len(cpg_output):,} CpGSite rows to {cpg_path}."
    )

    # The rule is a stable reference node. It is repeated per cohort output so
    # each cohort directory is self-contained; downstream Neo4j ingestion must
    # MERGE it on methylationStatusRuleId.
    rule_columns = node_property_names(node_map["MethylationStatusRule"])
    if rule_dataframe is None:
        rule_dataframe = pd.DataFrame(columns=rule_columns)

    rule_path = output_dir / "methylation_status_rules.csv"
    write_csv_atomically(rule_dataframe, rule_path)

    # ------------------------------------------------------------------
    # MethylationObservation and required relationship files
    # ------------------------------------------------------------------
    id_column, sample_columns = detect_matrix_columns(
        beta_file,
        cohort_name,
        selected_samples,
    )

    observation_final = output_dir / "methylation_observations.csv"
    sample_rel_final = (
        output_dir / "sample_has_methylation_observation.csv"
    )
    cpg_rel_final = output_dir / "methylation_observation_measures_cpg.csv"
    rule_rel_final = (
        output_dir / "methylation_observation_classified_using.csv"
    )

    observation_temp = Path(str(observation_final) + ".tmp")
    sample_rel_temp = Path(str(sample_rel_final) + ".tmp")
    cpg_rel_temp = Path(str(cpg_rel_final) + ".tmp")
    rule_rel_temp = Path(str(rule_rel_final) + ".tmp")

    for temp_path in [
        observation_temp,
        sample_rel_temp,
        cpg_rel_temp,
        rule_rel_temp,
    ]:
        remove_stale_temp_file(temp_path)

    observation_columns = node_property_names(
        node_map["MethylationObservation"]
    )
    sample_rel_columns = ["sampleId", "methylationObservationId"]
    cpg_rel_columns = ["methylationObservationId", "cpgId"]
    rule_rel_columns = [
        "methylationObservationId",
        "methylationStatusRuleId",
    ]

    first_observation_chunk = True
    first_sample_rel_chunk = True
    first_cpg_rel_chunk = True
    first_rule_rel_chunk = True

    total_observations = 0
    total_missing = 0
    total_non_numeric = 0
    total_out_of_range = 0
    seen_matrix_cpg_ids = set()

    try:
        reader = pd.read_csv(
            beta_file,
            usecols=[id_column, *sample_columns],
            chunksize=chunk_size,
            low_memory=False,
        )

        for chunk_number, chunk in enumerate(reader, start=1):
            chunk = chunk.rename(columns={id_column: "cpgId"})
            chunk["cpgId"] = chunk["cpgId"].astype("string").str.strip()

            if selected_cpgs is not None:
                chunk = chunk.loc[chunk["cpgId"].isin(selected_cpgs)].copy()
                if chunk.empty:
                    continue

            invalid_cpg = ~chunk["cpgId"].str.match(r"^(cg\d+|ch\..+|rs\d+)$", na=False)
            if invalid_cpg.any():
                examples = (
                    chunk.loc[invalid_cpg, "cpgId"]
                    .drop_duplicates()
                    .head(10)
                    .tolist()
                )
                print(
                    f"[{cohort_name}] WARNING: Dropping {invalid_cpg.sum()} unrecognized probes in beta-matrix chunk "
                    f"{chunk_number} (e.g. {examples})"
                )
                chunk = chunk[~invalid_cpg]

            duplicate_within_chunk = chunk["cpgId"].duplicated(keep=False)
            if duplicate_within_chunk.any():
                examples = (
                    chunk.loc[duplicate_within_chunk, "cpgId"]
                    .drop_duplicates()
                    .head(10)
                    .tolist()
                )
                raise ValueError(
                    f"[{cohort_name}] Duplicate CpG rows in beta-matrix chunk "
                    f"{chunk_number}: {examples}"
                )

            chunk_cpg_ids = set(chunk["cpgId"].astype(str))
            repeated = chunk_cpg_ids & seen_matrix_cpg_ids
            if repeated:
                raise ValueError(
                    f"[{cohort_name}] CpG IDs are repeated across beta-matrix "
                    f"chunks: {sorted(repeated)[:10]}"
                )

            unknown = chunk_cpg_ids - valid_cpg_ids
            if unknown:
                raise ValueError(
                    f"[{cohort_name}] Beta-matrix CpG IDs are absent from the "
                    f"CpGSite annotation output: {sorted(unknown)[:10]}"
                )

            seen_matrix_cpg_ids.update(chunk_cpg_ids)

            melted = chunk.melt(
                id_vars=["cpgId"],
                value_vars=sample_columns,
                var_name="sampleId",
                value_name="betaValue",
            )

            melted, counters = clean_melted_measurements(
                melted,
                cohort_name,
            )

            total_missing += counters["missing"]
            total_non_numeric += counters["nonNumeric"]
            total_out_of_range += counters["outOfRange"]

            if melted.empty:
                print(
                    f"[{cohort_name}] Chunk {chunk_number:,} has no valid beta "
                    "measurements after filtering."
                )
                continue

            observation_output = apply_observation_mapping(
                melted,
                observation_config,
                node_map["MethylationObservation"],
                cohort_name,
                beta_file,
                templates,
                execution_rule,
            )

            (
                sample_rel_output,
                cpg_rel_output,
                rule_rel_output,
            ) = build_relationship_chunks(
                observation_output,
                execution_rule,
            )

            append_csv_chunk(
                observation_output,
                observation_temp,
                first_observation_chunk,
            )
            append_csv_chunk(
                sample_rel_output,
                sample_rel_temp,
                first_sample_rel_chunk,
            )
            append_csv_chunk(
                cpg_rel_output,
                cpg_rel_temp,
                first_cpg_rel_chunk,
            )

            if execution_rule is not None:
                append_csv_chunk(
                    rule_rel_output,
                    rule_rel_temp,
                    first_rule_rel_chunk,
                )
                first_rule_rel_chunk = False

            first_observation_chunk = False
            first_sample_rel_chunk = False
            first_cpg_rel_chunk = False

            total_observations += len(observation_output)
            print(
                f"[{cohort_name}] Chunk {chunk_number:,}: wrote "
                f"{len(observation_output):,} observations "
                f"({total_observations:,} cumulative)."
            )

        if first_observation_chunk:
            pd.DataFrame(columns=observation_columns).to_csv(
                observation_temp,
                index=False,
            )
        if first_sample_rel_chunk:
            pd.DataFrame(columns=sample_rel_columns).to_csv(
                sample_rel_temp,
                index=False,
            )
        if first_cpg_rel_chunk:
            pd.DataFrame(columns=cpg_rel_columns).to_csv(
                cpg_rel_temp,
                index=False,
            )
        if first_rule_rel_chunk:
            pd.DataFrame(columns=rule_rel_columns).to_csv(
                rule_rel_temp,
                index=False,
            )

        os.replace(observation_temp, observation_final)
        os.replace(sample_rel_temp, sample_rel_final)
        os.replace(cpg_rel_temp, cpg_rel_final)
        os.replace(rule_rel_temp, rule_rel_final)

    except Exception:
        print(
            f"[{cohort_name}] Processing failed. Partial outputs remain only "
            "with the '.tmp' suffix and must not be ingested."
        )
        raise

    manifest = {
        "cohort": cohort_name,
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "schemaName": config.get("schemaName", "LifeSphere"),
        "sourceBetaFile": os.path.basename(beta_file),
        "sourceAnnotationFile": os.path.basename(rowdata_file),
        "selectedSampleCount": len(sample_columns),
        "selectedCpGCount": len(seen_matrix_cpg_ids),
        "materialisedObservationCount": total_observations,
        "methylationStatusRuleId": (
            execution_rule["methylationStatusRuleId"]
            if execution_rule is not None
            else None
        ),
        "filteredValues": {
            "missing": total_missing,
            "nonNumeric": total_non_numeric,
            "outsideZeroToOne": total_out_of_range,
        },
        "outputs": {
            "CpGSite": cpg_path.name,
            "MethylationObservation": observation_final.name,
            "MethylationStatusRule": rule_path.name,
            "HAS_METHYLATION_OBSERVATION": sample_rel_final.name,
            "MEASURES_CPG": cpg_rel_final.name,
            "CLASSIFIED_USING": rule_rel_final.name,
        },
    }

    manifest_path = output_dir / "methylation_standardisation_manifest.json"
    manifest_temp = Path(str(manifest_path) + ".tmp")
    remove_stale_temp_file(manifest_temp)
    with manifest_temp.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    os.replace(manifest_temp, manifest_path)

    print(
        f"[{cohort_name}] Completed: {total_observations:,} materialised "
        "MethylationObservation rows."
    )
    print(
        f"[{cohort_name}] Filtered beta values — missing: "
        f"{total_missing:,}; non-numeric: {total_non_numeric:,}; "
        f"outside [0, 1]: {total_out_of_range:,}."
    )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Standardise TCGA methylation matrices into LifeSphere "
            "CpGSite, MethylationObservation, MethylationStatusRule, and "
            "relationship CSVs using the machine-readable schema as a "
            "runtime contract."
        )
    )

    parser.add_argument(
        "--data-dir",
        default=(
            "/rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/THESIS/TCGA_methylation_data"
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=(
            "/rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/THESIS/"
            "data_standardisation/outputs"
        ),
    )
    parser.add_argument(
        "--config",
        default=(
            "/rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/THESIS/JSON/"
            "tcga_methylation_mapping.json"
        ),
    )
    parser.add_argument(
        "--schema",
        default=(
            "/rds/projects/r/ranaaaa-ai-hackathon/Lifesphere/Shalini/lifesphere/"
            "lifesphere_schema.json"
        ),
        help="Path to the machine-readable LifeSphere schema JSON.",
    )
    parser.add_argument(
        "--cohort",
        default=None,
        help="Optionally process one cohort, for example TCGA-ACC.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help=(
            "Number of CpG rows read before melting. Reduce this for cohorts "
            "with many sample columns or limited memory."
        ),
    )
    parser.add_argument(
        "--sample-list",
        default=None,
        help=(
            "Optional one-column file of sample IDs to materialise. Without "
            "this and --cpg-list, all valid matrix measurements are written to "
            "the external staging CSV."
        ),
    )
    parser.add_argument(
        "--cpg-list",
        default=None,
        help=(
            "Optional one-column file of CpG IDs to materialise. This supports "
            "the schema policy of keeping dense matrices external and loading "
            "only selected graph-resident observations."
        ),
    )

    args = parser.parse_args()

    if args.chunk_size <= 0:
        parser.error("--chunk-size must be a positive integer.")

    return args


def main():
    args = parse_args()

    config = load_json(args.config, "Methylation mapping configuration")
    schema = load_json(args.schema, "LifeSphere schema JSON")
    node_map, _ = validate_schema_contract(schema)

    # Add schema metadata to the manifest without changing the biological map.
    config.setdefault("schemaName", schema.get("schemaName", "LifeSphere"))

    templates = import_transform_templates()

    selected_samples = read_identifier_file(args.sample_list)
    selected_cpgs = read_identifier_file(args.cpg_list)

    if selected_samples is None and selected_cpgs is None:
        print(
            "Warning: no sample/CpG materialisation filter was supplied. The "
            "script will create a complete long-format external staging file. "
            "The LifeSphere schema recommends loading only selected, "
            "query-relevant observations into Neo4j rather than the complete "
            "dense methylation matrix."
        )

    data_dir = Path(args.data_dir).expanduser()
    output_dir = Path(args.out_dir).expanduser()

    if not data_dir.is_dir():
        raise FileNotFoundError(f"Input data directory was not found: {data_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    if args.cohort:
        cohort_dir = data_dir / args.cohort
        if not cohort_dir.is_dir():
            raise FileNotFoundError(
                f"Cohort directory was not found: {cohort_dir}"
            )

        process_cohort(
            str(cohort_dir),
            str(output_dir),
            config,
            node_map,
            templates,
            args.chunk_size,
            selected_samples,
            selected_cpgs,
        )
        return

    cohorts = sorted(
        entry.name
        for entry in data_dir.iterdir()
        if entry.is_dir() and entry.name.startswith("TCGA-")
    )

    if not cohorts:
        raise FileNotFoundError(
            f"No TCGA-* cohort directories were found in {data_dir}."
        )

    print(f"Found {len(cohorts)} TCGA cohorts to process.")
    failed_cohorts = []

    for cohort in cohorts:
        try:
            process_cohort(
                str(data_dir / cohort),
                str(output_dir),
                config,
                node_map,
                templates,
                args.chunk_size,
                selected_samples,
                selected_cpgs,
            )
        except Exception as exc:
            failed_cohorts.append(cohort)
            print(f"Error processing {cohort}: {exc}")
            traceback.print_exc()

    successful = len(cohorts) - len(failed_cohorts)
    print(
        f"\nCompleted processing: {successful} successful, "
        f"{len(failed_cohorts)} failed."
    )

    if failed_cohorts:
        print("Failed cohorts: " + ", ".join(failed_cohorts))
        raise SystemExit(1)


if __name__ == "__main__":
    main()