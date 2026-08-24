"""File-backed CSV and Parquet source adapters."""

from pathlib import Path
from typing import Any, cast

import polars as pl

from etlonomy.adapters.base import AdapterSource, project_and_rename
from etlonomy.exceptions import DatasetProviderError


class CsvAdapter:
    """Read CSV files lazily and apply logical projection immediately."""

    def read(self, source: AdapterSource, columns: tuple[str, ...]) -> pl.LazyFrame:
        """Return requested columns from a CSV source as a lazy frame."""
        path = _required_path(source)
        try:
            options = cast(dict[str, Any], dict(source.options))
            frame = pl.scan_csv(path, **options)
            return project_and_rename(frame, columns, source.columns)
        except (OSError, pl.exceptions.PolarsError) as error:
            raise DatasetProviderError(
                f'Unable to read CSV source {path}: {error}'
            ) from error


class ParquetAdapter:
    """Read Parquet files lazily and apply logical projection immediately."""

    def read(self, source: AdapterSource, columns: tuple[str, ...]) -> pl.LazyFrame:
        """Return requested columns from a Parquet source as a lazy frame."""
        path = _required_path(source)
        try:
            options = cast(dict[str, Any], dict(source.options))
            frame = pl.scan_parquet(path, **options)
            return project_and_rename(frame, columns, source.columns)
        except (OSError, pl.exceptions.PolarsError) as error:
            raise DatasetProviderError(
                f'Unable to read Parquet source {path}: {error}'
            ) from error


def _required_path(source: AdapterSource) -> Path:
    if not source.source_uri:
        raise DatasetProviderError(f'{source.source_type} source requires a source URI')
    path = Path(source.source_uri)
    if not path.is_file():
        raise DatasetProviderError(f'Source file does not exist: {path}')
    return path
