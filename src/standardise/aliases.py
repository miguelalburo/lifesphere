"""Column-alias detection for the standardisation pipeline.

Source datasets often label the same concept with different column names
(``bcr_patient_uuid`` vs ``case_id``, ``project.project_id`` vs ``project_id``).
Rather than fork a schema per source, canonical names and their known aliases are
declared in ``config/schemas/aliases.json`` and every recognised alias is
rewritten to its canonical form *before* schema matching runs — so entities.json
and edges.json only ever reference canonical column names.

aliases.json format:
    { "<canonical_name>": ["<alias>", "<alias>", ...], ... }

Alias matching is case-insensitive and ignores surrounding whitespace. Canonical
names are never remapped, so an alias that collides with a real canonical column
elsewhere in the schema is a config error the maintainer must avoid.
"""

import json
import sys
from pathlib import Path


def _norm(col: str) -> str:
    return (col or "").strip().lower()


def load_alias_map(schema_dir: Path) -> dict[str, str]:
    """Return a lookup of ``normalised_alias -> canonical_name``.

    A missing ``aliases.json`` is non-fatal: an empty map is returned and no
    renaming happens.  Aliases that resolve to conflicting canonical names are
    reported and the first mapping wins.
    """
    p = schema_dir / "aliases.json"
    if not p.exists():
        print(f"  ! {p} not found — no column-alias renaming applied", file=sys.stderr)
        return {}
    with open(p) as f:
        raw: dict[str, list[str]] = json.load(f)

    alias_map: dict[str, str] = {}
    for canonical, aliases in raw.items():
        for alias in aliases:
            key = _norm(alias)
            if key in alias_map and alias_map[key] != canonical:
                print(
                    f"  ! alias '{alias}' maps to both '{alias_map[key]}' and "
                    f"'{canonical}' — keeping '{alias_map[key]}'",
                    file=sys.stderr,
                )
                continue
            alias_map[key] = canonical
    return alias_map


def canonicalise(columns: list[str], alias_map: dict[str, str]) -> list[str]:
    """Rewrite any aliased column in ``columns`` to its canonical name.

    Columns already matching a canonical name — or entirely unknown — are left
    untouched.  When two source columns collapse onto the same canonical name a
    warning is emitted; the downstream ``csv.DictReader`` then keeps the last
    such column's value per row.
    """
    out: list[str] = []
    origin: dict[str, str] = {}
    for col in columns:
        canon = alias_map.get(_norm(col), col)
        if canon != col:
            print(f"  · alias: '{col}' -> '{canon}'", file=sys.stderr)
        if canon in origin and origin[canon] != col:
            print(
                f"  ! alias: columns '{origin[canon]}' and '{col}' both map to "
                f"'{canon}' — later column wins per row",
                file=sys.stderr,
            )
        origin[canon] = col
        out.append(canon)
    return out
