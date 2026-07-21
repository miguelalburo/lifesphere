"""Reshape pre-pass: melt traditional inputs into canonical observation TSVs.

Public surface is the single door :func:`reshape_dataset`; :func:`parse_specs`
turns a profile's raw ``reshape:`` block into structured specs for it. All melt /
VCF internals live behind the door.
"""

from .door import reshape_dataset
from .spec import ReshapeSpec, parse_specs

__all__ = ["reshape_dataset", "parse_specs", "ReshapeSpec"]
