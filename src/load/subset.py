"""Filter standardised CSVs to a subset of TCGA projects (v2 schema).

Usage:
    python3 -m src.load.subset <input_dir> <output_dir> --projects TCGA-BRCA TCGA-LUAD ...

Walks the subject → child-node graph to collect every entity that belongs to the
selected projects, then writes filtered copies of all node and edge CSVs.
"""

import argparse
import csv
import shutil
from pathlib import Path


def _read_col(path: Path, col: str) -> set[str]:
    with open(path, newline="") as f:
        return {row[col] for row in csv.DictReader(f) if row.get(col)}


def _filter(src: Path, dst: Path, col: str, keep: set[str]) -> int:
    if not src.exists():
        return 0
    n = 0
    with open(src, newline="") as fin, open(dst, "w", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in reader:
            if row.get(col) in keep:
                writer.writerow(row)
                n += 1
    return n


def _filter_edge(src: Path, dst: Path, src_ids: set[str]) -> tuple[int, set[str]]:
    """Keep rows where source_id is in src_ids; return (rows_written, unique_target_ids)."""
    if not src.exists():
        return 0, set()
    targets: set[str] = set()
    n = 0
    with open(src, newline="") as fin, open(dst, "w", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if row["source_id"] in src_ids:
                writer.writerow(row)
                targets.add(row["target_id"])
                n += 1
    return n, targets


def run(input_dir: Path, output_dir: Path, projects: list[str]) -> None:
    proj_set = set(projects)
    ni = input_dir / "nodes"
    ei = input_dir / "edges"
    no = output_dir / "nodes"
    eo = output_dir / "edges"
    no.mkdir(parents=True, exist_ok=True)
    eo.mkdir(parents=True, exist_ok=True)

    stats: dict[str, int] = {}

    # ── Study (project-level nodes) ───────────────────────────────────────────
    stats["Study"] = _filter(ni / "Study.csv", no / "Study.csv", "id", proj_set)

    # ── HAS_STUDY: source=program_id, target=study_id ─────────────────────────
    # Filter by target_id (study_id) in proj_set; collect referenced program_ids.
    program_ids: set[str] = set()
    has_study_rows: list[dict] = []
    with open(ei / "HAS_STUDY.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["target_id"] in proj_set:
                has_study_rows.append(row)
                program_ids.add(row["source_id"])
    with open(eo / "HAS_STUDY.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source_id", "target_id"])
        w.writeheader()
        w.writerows(has_study_rows)
    stats["HAS_STUDY"] = len(has_study_rows)

    # ── Program ───────────────────────────────────────────────────────────────
    stats["Program"] = _filter(ni / "Program.csv", no / "Program.csv", "id", program_ids)

    # ── Subjects in selected projects ─────────────────────────────────────────
    subject_ids: set[str] = set()
    with open(ei / "HAS_SUBJECT.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["source_id"] in proj_set:
                subject_ids.add(row["target_id"])

    stats["Subject"] = _filter(ni / "Subject.csv", no / "Subject.csv", "id", subject_ids)
    n, _ = _filter_edge(ei / "HAS_SUBJECT.csv", eo / "HAS_SUBJECT.csv", proj_set)
    stats["HAS_SUBJECT"] = n

    # ── Subject → Diagnosis ───────────────────────────────────────────────────
    n, diagnosis_ids = _filter_edge(ei / "HAS_DIAGNOSIS.csv", eo / "HAS_DIAGNOSIS.csv", subject_ids)
    stats["HAS_DIAGNOSIS"] = n
    stats["Diagnosis"] = _filter(ni / "Diagnosis.csv", no / "Diagnosis.csv", "id", diagnosis_ids)

    # ── Subject → Survival ────────────────────────────────────────────────────
    n, survival_ids = _filter_edge(
        ei / "HAS_SURVIVAL_RECORD.csv", eo / "HAS_SURVIVAL_RECORD.csv", subject_ids
    )
    stats["HAS_SURVIVAL_RECORD"] = n
    stats["Survival"] = _filter(ni / "Survival.csv", no / "Survival.csv", "id", survival_ids)

    # ── Subject → Sample (PROVIDED_SAMPLE) ───────────────────────────────────
    n, sample_ids = _filter_edge(
        ei / "PROVIDED_SAMPLE.csv", eo / "PROVIDED_SAMPLE.csv", subject_ids
    )
    stats["PROVIDED_SAMPLE"] = n
    stats["Sample"] = _filter(ni / "Sample.csv", no / "Sample.csv", "id", sample_ids)

    # ── Sample → ExperimentalCondition ───────────────────────────────────────
    n, condition_ids = _filter_edge(
        ei / "HAS_CONDITION.csv", eo / "HAS_CONDITION.csv", sample_ids
    )
    stats["HAS_CONDITION"] = n
    stats["ExperimentalCondition"] = _filter(
        ni / "ExperimentalCondition.csv", no / "ExperimentalCondition.csv",
        "id", condition_ids
    )

    # ── Sample → Intervention (UNDERWENT_INTERVENTION) ───────────────────────
    n, intervention_ids = _filter_edge(
        ei / "UNDERWENT_INTERVENTION.csv", eo / "UNDERWENT_INTERVENTION.csv", sample_ids
    )
    stats["UNDERWENT_INTERVENTION"] = n
    stats["Intervention"] = _filter(
        ni / "Intervention.csv", no / "Intervention.csv", "id", intervention_ids
    )

    # ── Diagnosis → PathologyDetail ───────────────────────────────────────────
    n, pathology_ids = _filter_edge(
        ei / "HAS_PATHOLOGY.csv", eo / "HAS_PATHOLOGY.csv", diagnosis_ids
    )
    stats["HAS_PATHOLOGY"] = n
    stats["PathologyDetail"] = _filter(
        ni / "PathologyDetail.csv", no / "PathologyDetail.csv", "id", pathology_ids
    )

    # ── Diagnosis → PhenotypeObservation ─────────────────────────────────────
    n, phenotype_ids = _filter_edge(
        ei / "HAS_PHENOTYPE_OBSERVATION.csv", eo / "HAS_PHENOTYPE_OBSERVATION.csv",
        diagnosis_ids
    )
    stats["HAS_PHENOTYPE_OBSERVATION"] = n
    stats["PhenotypeObservation"] = _filter(
        ni / "PhenotypeObservation.csv", no / "PhenotypeObservation.csv",
        "id", phenotype_ids
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    node_types = {
        "Program", "Study", "Subject", "Diagnosis", "Survival",
        "Sample", "ExperimentalCondition", "Intervention",
        "PathologyDetail", "PhenotypeObservation",
    }
    edge_types = {k for k in stats if k not in node_types}

    total_nodes = sum(v for k, v in stats.items() if k in node_types)
    total_edges = sum(v for k, v in stats.items() if k in edge_types)

    print(f"\nSubset written to {output_dir}")
    print(f"  nodes: {total_nodes:>8,}")
    for k in sorted(node_types):
        if k in stats:
            print(f"    {k:<30s} {stats[k]:>8,}")
    print(f"  edges: {total_edges:>8,}")
    for k in sorted(edge_types):
        if k in stats:
            print(f"    {k:<30s} {stats[k]:>8,}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input_dir",  type=Path)
    p.add_argument("output_dir", type=Path)
    p.add_argument("--projects", nargs="+", required=True,
                   metavar="PROJECT", help="TCGA project IDs e.g. TCGA-BRCA TCGA-LUAD")
    args = p.parse_args(argv)
    run(args.input_dir, args.output_dir, args.projects)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
