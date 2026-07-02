"""BioCypher adapter over the standardised CSVs.

Table-driven: every ``nodes/{Label}.csv`` becomes nodes labelled ``Label``; every
``edges/{LABEL}.csv`` becomes edges labelled ``LABEL``. The label is matched to the
``input_label`` declared in ``config/schema_config.yaml``.

Yields the tuple shapes BioCypher expects:
    node:  (id, label, properties)
    edge:  (id, source_id, target_id, label, properties)

Pure-``csv``; no BioCypher import here, so the adapter is unit-testable standalone.
"""

import csv
from pathlib import Path
from typing import Iterator

NodeTuple = tuple[str, str, dict]
EdgeTuple = tuple[str, str, str, str, dict]


class StandardisedCSVAdapter:
    """Streams nodes/edges from a ``data/standardised/<base>`` directory."""

    def __init__(self, input_dir: Path):
        self.input_dir = Path(input_dir)
        self.nodes_dir = self.input_dir / "nodes"
        self.edges_dir = self.input_dir / "edges"

    def get_nodes(self) -> Iterator[NodeTuple]:
        for path in sorted(self.nodes_dir.glob("*.csv")):
            label = path.stem
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    node_id = row.pop("id", "")
                    if not node_id:
                        continue
                    # Keep every column (empties included) so all nodes of a label
                    # share one property schema — BioCypher's batch writer requires
                    # consistent keys per label when properties aren't declared.
                    yield node_id, label, dict(row)

    def get_edges(self) -> Iterator[EdgeTuple]:
        for path in sorted(self.edges_dir.glob("*.csv")):
            label = path.stem
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    source_id = row.get("source_id", "")
                    target_id = row.get("target_id", "")
                    if not source_id or not target_id:
                        continue
                    props = {k: v for k, v in row.items()
                             if k not in ("source_id", "target_id") and v != ""}
                    # id=None -> BioCypher derives a deterministic relationship id.
                    yield "", source_id, target_id, label, props
