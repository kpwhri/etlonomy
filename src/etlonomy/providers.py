"""Dataset-provider interfaces and the isolated provider used by tests."""

from collections.abc import Mapping
from typing import Protocol

import polars as pl

from etlonomy.exceptions import MissingTestColumnError, MissingTestDatasetError
from etlonomy.models import DatasetId, ExecutionContext, ExternalRead, Read


class DatasetProvider(Protocol):
    """Resolve logical read requests into Polars lazy frames."""

    def read(self, request: Read, context: ExecutionContext) -> pl.LazyFrame:
        """Resolve and return a logical dataset read request."""
        ...


class ExternalDatasetProvider(Protocol):
    """Resolve datasets managed by a system outside Etlonomy."""

    def read(self, request: ExternalRead, context: ExecutionContext) -> object:
        """Resolve and return an external dataset read request."""
        ...


class TestDatasetProvider:
    """Serve only explicitly supplied in-memory datasets during tests.

    Missing datasets fail immediately. This provider has no catalog or fallback
    provider and therefore cannot reach production data.
    """

    __test__ = False

    def __init__(
            self, datasets: Mapping[DatasetId, pl.DataFrame | pl.LazyFrame]
    ) -> None:
        """Create a provider exposing exactly the supplied test datasets."""
        self._datasets = dict(datasets)

    def read(self, request: Read, context: ExecutionContext) -> pl.LazyFrame:
        """Select requested columns from an explicitly supplied test dataset.

        Raises:
            MissingTestDatasetError: If no fixture was supplied for the dataset.
            MissingTestColumnError: If a requested logical column is absent.

        """
        del context
        try:
            fixture = self._datasets[request.dataset]
        except KeyError as error:
            raise MissingTestDatasetError(
                f'no test dataset supplied for {request.dataset}'
            ) from error

        frame = fixture.lazy() if isinstance(fixture, pl.DataFrame) else fixture
        available = set(frame.collect_schema().names())
        missing = [column for column in request.columns if column not in available]
        if missing:
            names = ', '.join(missing)
            raise MissingTestColumnError(
                f'test dataset {request.dataset} is missing requested columns: {names}'
            )
        return frame.select(request.columns)
