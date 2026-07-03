"""Filter standardised CSVs to a subset of TCGA projects.

Usage:
    python3 -m src.load.subset <input_dir> <output_dir> --projects TCGA-BRCA TCGA-LUAD ...
"""

import argparse
import csv
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def _read_ids(path: Path, id_col: str) -> set[str]:
    with open(path, newline="") as f:
        return {row[id_col] for row in csv.DictReader(f) if row.get(id_col)}


def _filter_csv(src: Path, dst: Path, id_col: str, keep: set[str]) -> int:
    with open(src, newline="") as fin, open(dst, "w", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        kept = 0
        for row in reader:
            if row.get(id_col) in keep:
                writer.writerow(row)
                kept += 1
    return kept


def run(input_dir: Path, output_dir: Path, projects: list[str]) -> None:
    proj_set = set(projects)
    nodes_in = input_dir / "nodes"
    edges_in = input_dir / "edges"
    nodes_out = output_dir / "nodes"
    edges_out = output_dir / "edges"
    nodes_out.mkdir(parents=True, exist_ok=True)
    edges_out.mkdir(parents=True, exist_ok=True)

    # --- Program + Project (keep all programs; keep only selected projects) ---
    shutil.copy(nodes_in / "Program.csv", nodes_out / "Program.csv")
    n = _filter_csv(nodes_in / "Project.csv", nodes_out / "Project.csv", "id", proj_set)
    log.info("Project: %d", n)

    # --- HAS_PROJECT edges ---
    n = _filter_csv(edges_in / "HAS_PROJECT.csv", edges_out / "HAS_PROJECT.csv", "target_id", proj_set)
    log.info("HAS_PROJECT: %d", n)

    # --- Subjects enrolled in selected projects ---
    subject_ids: set[str] = set()
    with open(edges_in / "ENROLLS.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["source_id"] in proj_set:
                subject_ids.add(row["target_id"])
    log.info("Subjects selected: %d", len(subject_ids))

    n = _filter_csv(nodes_in / "Subject.csv", nodes_out / "Subject.csv", "id", subject_ids)
    log.info("Subject nodes: %d", n)
    n = _filter_csv(edges_in / "ENROLLS.csv", edges_out / "ENROLLS.csv", "target_id", subject_ids)
    log.info("ENROLLS: %d", n)

    # Helper: filter an edge file by subject (source), collect target IDs
    def filter_subject_edge(edge_name: str) -> set[str]:
        src = edges_in / f"{edge_name}.csv"
        dst = edges_out / f"{edge_name}.csv"
        target_ids: set[str] = set()
        with open(src, newline="") as fin, open(dst, "w", newline="") as fout:
            reader = csv.DictReader(fin)
            writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                if row["source_id"] in subject_ids:
                    writer.writerow(row)
                    target_ids.add(row["target_id"])
        log.info("%s: %d edges", edge_name, len(target_ids))
        return target_ids

    # --- Subject → child nodes ---
    diagnosis_ids   = filter_subject_edge("HAS_DIAGNOSIS")
    phenotype_ids   = filter_subject_edge("HAS_PHENOTYPE_OBSERVATION")
    followup_ids    = filter_subject_edge("HAS_FOLLOWUP")
    sample_ids      = filter_subject_edge("PROVIDED_SAMPLE")

    _filter_csv(nodes_in / "Diagnosis.csv",           nodes_out / "Diagnosis.csv",           "id", diagnosis_ids)
    _filter_csv(nodes_in / "PhenotypeObservation.csv", nodes_out / "PhenotypeObservation.csv", "id", phenotype_ids)
    _filter_csv(nodes_in / "FollowUp.csv",            nodes_out / "FollowUp.csv",            "id", followup_ids)
    _filter_csv(nodes_in / "Sample.csv",              nodes_out / "Sample.csv",              "id", sample_ids)
    log.info("Diagnosis/PhenotypeObservation/FollowUp/Sample nodes written")

    # Helper: filter an edge file by a set of source IDs, collect target IDs
    def filter_edge(edge_name: str, source_ids: set[str]) -> set[str]:
        src = edges_in / f"{edge_name}.csv"
        dst = edges_out / f"{edge_name}.csv"
        target_ids: set[str] = set()
        with open(src, newline="") as fin, open(dst, "w", newline="") as fout:
            reader = csv.DictReader(fin)
            writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                if row["source_id"] in source_ids:
                    writer.writerow(row)
                    target_ids.add(row["target_id"])
        log.info("%s: %d edges", edge_name, len(target_ids))
        return target_ids

    # --- Diagnosis → Treatment + PathologyDetail ---
    treatment_ids = filter_edge("HAS_TREATMENT", diagnosis_ids)
    pathology_ids = filter_edge("HAS_PATHOLOGY", diagnosis_ids)
    _filter_csv(nodes_in / "Treatment.csv",       nodes_out / "Treatment.csv",       "id", treatment_ids)
    _filter_csv(nodes_in / "PathologyDetail.csv", nodes_out / "PathologyDetail.csv", "id", pathology_ids)
    log.info("Treatment/PathologyDetail nodes written")

    # --- FollowUp → MolecularTest ---
    moltest_ids = filter_edge("HAS_MOLECULAR_TEST", followup_ids)
    _filter_csv(nodes_in / "MolecularTest.csv", nodes_out / "MolecularTest.csv", "id", moltest_ids)
    log.info("MolecularTest nodes written")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="Subset standardised KG CSVs to selected TCGA projects.")
    p.add_argument("input_dir",  type=Path)
    p.add_argument("output_dir", type=Path)
    p.add_argument("--projects", nargs="+", required=True)
    args = p.parse_args(argv)
    run(args.input_dir, args.output_dir, args.projects)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
