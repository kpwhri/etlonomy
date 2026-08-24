"""SAS7BDAT adapter with an injectable eager reader boundary."""

from collections.abc import Callable
from pathlib import Path

import polars as pl

from etlonomy.adapters.base import (
    AdapterSource,
    as_lazy_frame,
    physical_columns,
    project_and_rename,
)
from etlonomy.exceptions import DatasetProviderError

SasReader = Callable[[Path, tuple[str, ...]], pl.DataFrame | pl.LazyFrame]


class SasAdapter:
    """Read selected SAS columns through an explicitly configured reader."""

    def __init__(self, reader: SasReader | None = None) -> None:
        """Use an injected reader or the optional pyreadstat implementation."""
        self._reader = reader or _default_sas_reader

    def read(self, source: AdapterSource, columns: tuple[str, ...]) -> pl.LazyFrame:
        """Read selected physical columns and expose their logical names."""
        if not source.source_uri:
            raise DatasetProviderError('sas7bdat source requires a source URI')
        path = Path(source.source_uri)
        if not path.is_file():
            raise DatasetProviderError(f'Source file does not exist: {path}')
        requested = physical_columns(columns, source.columns)
        try:
            frame = as_lazy_frame(self._reader(path, requested))
            return project_and_rename(frame, columns, source.columns)
        except (OSError, KeyError, pl.exceptions.PolarsError) as error:
            raise DatasetProviderError(
                f'Unable to read SAS7BDAT source {path}: {error}'
            ) from error


def _default_sas_reader(path: Path, columns: tuple[str, ...]) -> pl.DataFrame:
    try:
        import pyreadstat
    except ImportError as error:
        raise DatasetProviderError(
            'SAS7BDAT support requires the etlonomy sas extra'
        ) from error
    try:
        values, _ = pyreadstat.read_sas7bdat(
            path,
            usecols=list(columns),
            output_format='dict',
        )
    except (pyreadstat.PyreadstatError, pyreadstat.ReadstatError) as error:
        raise DatasetProviderError(
            f'Unable to read SAS7BDAT source {path}: {error}'
        ) from error
    return pl.DataFrame(values)
