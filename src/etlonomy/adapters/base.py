"""Shared contracts and helpers for physical dataset adapters."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import polars as pl


@dataclass(frozen=True, slots=True)
class AdapterSource:
    """Describe the physical source selected from a catalog version."""

    source_type: str
    source_uri: str | None
    query: str | None = None
    credential_ref: str | None = None
    options: Mapping[str, object] = field(default_factory=dict)
    columns: Mapping[str, str] = field(default_factory=dict)


class SourceAdapter(Protocol):
    """Read one resolved physical source using logical column names."""

    def read(self, source: AdapterSource, columns: tuple[str, ...]) -> pl.LazyFrame:
        """Return a lazy frame projected to the requested logical columns."""
        ...


def physical_columns(
        columns: tuple[str, ...], mappings: Mapping[str, str]
) -> tuple[str, ...]:
    """Map requested logical names to physical source names."""
    return tuple(mappings.get(column, column) for column in columns)


def project_and_rename(
        frame: pl.LazyFrame, columns: tuple[str, ...], mappings: Mapping[str, str]
) -> pl.LazyFrame:
    """Project physical columns and restore their requested logical names."""
    expressions = [
        pl.col(mappings.get(column, column)).alias(column) for column in columns
    ]
    projected = frame.select(expressions)
    projected.collect_schema()
    return projected


def as_lazy_frame(value: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    """Convert an executor or reader result to a lazy frame."""
    return value.lazy() if isinstance(value, pl.DataFrame) else value
