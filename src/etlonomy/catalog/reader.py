"""Read and temporally resolve metadata from a compiled SQLite catalog."""

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType

from etlonomy.catalog.migrations import CURRENT_SCHEMA_VERSION
from etlonomy.exceptions import (
    CatalogError,
    DatasetNotFoundError,
    DatasetVersionNotFoundError,
)
from etlonomy.manifest import ColumnManifest
from etlonomy.models import DatasetId


@dataclass(frozen=True, slots=True)
class ResolvedDataset:
    """Represent one resolved physical implementation of a logical dataset."""

    dataset_version_id: int
    dataset: DatasetId
    version: int
    valid_from: date
    valid_to: date | None
    source_type: str
    source_uri: str | None
    source_root: str | None
    connection: str | None
    credential_ref: str | None
    query: str | None
    options: Mapping[str, object]
    description: str | None
    columns: tuple[ColumnManifest, ...] | None = None

    def __post_init__(self) :
        """Protect resolved source options from caller mutation."""
        object.__setattr__(self, 'options', MappingProxyType(dict(self.options)))


class SQLiteCatalog:
    """Provide read-only logical and temporal queries over a SQLite catalog."""

    def __init__(self, path: Path) :
        """Store the compiled catalog path without opening a persistent connection."""
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise CatalogError(f'catalog does not exist: {self.path}')
        uri = f'{self.path.resolve().as_uri()}?mode=ro'
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                'SELECT MAX(version) AS version FROM schema_version'
            ).fetchone()
            version = None if row is None else row['version']
            if version != CURRENT_SCHEMA_VERSION:
                raise CatalogError(
                    f'catalog schema version is {version!r}; expected '
                    f'{CURRENT_SCHEMA_VERSION}. Rebuild the catalog.'
                )
            connection.execute('PRAGMA foreign_keys = ON')
            return connection
        except CatalogError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as error:
            if connection is not None:
                connection.close()
            raise CatalogError(f'cannot open catalog {self.path}: {error}') from error

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        except sqlite3.Error as error:
            raise CatalogError(f'cannot query catalog {self.path}: {error}') from error
        finally:
            connection.close()

    def list_datasets(self) -> tuple[DatasetId, ...]:
        """Return all logical datasets in canonical-name order."""
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT canonical_name FROM datasets ORDER BY canonical_name'
            ).fetchall()
        return tuple(DatasetId.parse(row['canonical_name']) for row in rows)

    def get_dataset(self, dataset: DatasetId) -> tuple[int, str | None]:
        """Return the internal identifier and description for a logical dataset."""
        with self._connection() as connection:
            row = connection.execute(
                'SELECT dataset_id, description FROM datasets WHERE canonical_name = ?',
                (str(dataset),),
            ).fetchone()
        if row is None:
            raise DatasetNotFoundError(f'dataset not found: {dataset}')
        return int(row['dataset_id']), row['description']

    def get_versions(self, dataset: DatasetId) -> tuple[ResolvedDataset, ...]:
        """Return all versions of a dataset ordered by validity start."""
        dataset_id, _ = self.get_dataset(dataset)
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT * FROM dataset_versions WHERE dataset_id = ? '
                'ORDER BY valid_from, version',
                (dataset_id,),
            ).fetchall()
        resolved = []
        for row in rows:
            item = self._resolved(dataset, row)
            columns = self.get_optional_columns(item.dataset_version_id)
            resolved.append(
                ResolvedDataset(
                    dataset_version_id=item.dataset_version_id,
                    dataset=item.dataset,
                    version=item.version,
                    valid_from=item.valid_from,
                    valid_to=item.valid_to,
                    source_type=item.source_type,
                    source_uri=item.source_uri,
                    source_root=item.source_root,
                    connection=item.connection,
                    credential_ref=item.credential_ref,
                    query=item.query,
                    options=item.options,
                    description=item.description,
                    columns=columns or None,
                )
            )
        return tuple(resolved)

    @staticmethod
    def _resolved(dataset: DatasetId, row: sqlite3.Row) -> ResolvedDataset:
        return ResolvedDataset(
            dataset_version_id=int(row['dataset_version_id']),
            dataset=dataset,
            version=int(row['version']),
            valid_from=date.fromisoformat(row['valid_from']),
            valid_to=date.fromisoformat(row['valid_to']) if row['valid_to'] else None,
            source_type=row['source_type'],
            source_uri=row['source_uri'],
            source_root=row['source_root'],
            connection=row['connection_name'],
            credential_ref=row['credential_ref'],
            query=row['query'],
            options=json.loads(row['options_json'] or '{}'),
            description=row['description'],
        )

    def resolve_dataset(
            self,
            dataset: DatasetId,
            as_of: date | None = None,
            version: int | None = None,
    ) -> ResolvedDataset:
        """Resolve an explicit version or the version valid on a requested date.

        Omitting ``as_of`` uses today's date. If the catalog has no version valid
        today, the most recently started historical version is returned. This makes
        the normal current-data path concise while retaining explicit historical
        reproducibility.
        """
        versions = self.get_versions(dataset)
        resolution_date = as_of or date.today()
        for candidate in versions:
            if version is not None:
                if candidate.version == version:
                    return candidate
            elif candidate.valid_from <= resolution_date and (
                    candidate.valid_to is None or resolution_date < candidate.valid_to
            ):
                return candidate
        if version is None and as_of is None:
            historical = [
                candidate
                for candidate in versions
                if candidate.valid_from <= resolution_date
            ]
            if historical:
                return historical[-1]
        detail = (
            f'version {version}'
            if version is not None
            else f'date {resolution_date.isoformat()}'
        )
        raise DatasetVersionNotFoundError(f'no {detail} found for {dataset}')

    def get_dependencies(self, dataset_version_id: int) -> tuple[DatasetId, ...]:
        """Return declared upstream datasets for a physical dataset version."""
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT d.canonical_name FROM dataset_dependencies AS dep '
                'JOIN datasets AS d ON d.dataset_id = dep.upstream_dataset_id '
                'WHERE dep.dataset_version_id = ? ORDER BY d.canonical_name',
                (dataset_version_id,),
            ).fetchall()
        return tuple(DatasetId.parse(row['canonical_name']) for row in rows)

    def get_optional_columns(
            self, dataset_version_id: int
    ) -> tuple[ColumnManifest, ...]:
        """Return optional column metadata for a physical dataset version."""
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT * FROM dataset_columns WHERE dataset_version_id = ? ORDER BY logical_name',
                (dataset_version_id,),
            ).fetchall()
        return tuple(
            ColumnManifest(
                logical_name=row['logical_name'],
                source_name=row['source_name'],
                data_type=row['data_type'],
                nullable=None if row['nullable'] is None else bool(row['nullable']),
                description=row['description'],
            )
            for row in rows
        )

    def get_environment(self) -> str | None:
        """Return the optional environment identity compiled into the catalog."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM catalog_metadata WHERE key = 'environment'"
            ).fetchone()
        return None if row is None else str(row['value'])

    def get_root(self, name: str) -> str:
        """Return the base URI for a named file root."""
        with self._connection() as connection:
            row = connection.execute(
                'SELECT base_uri FROM roots WHERE root_name = ?', (name,)
            ).fetchone()
        if row is None:
            raise DatasetNotFoundError(f'file root not found: {name}')
        return str(row['base_uri'])

    def get_connection(self, name: str) -> tuple[str, str | None]:
        """Return a named SQLAlchemy URL and optional credential reference."""
        with self._connection() as connection:
            row = connection.execute(
                'SELECT sqlalchemy_url, credential_ref FROM connections '
                'WHERE connection_name = ?',
                (name,),
            ).fetchone()
        if row is None:
            raise DatasetNotFoundError(f'connection not found: {name}')
        return str(row['sqlalchemy_url']), row['credential_ref']

    def list_roots(self) -> tuple[tuple[str, str], ...]:
        """Return configured file roots in name order."""
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT root_name, base_uri FROM roots ORDER BY root_name'
            ).fetchall()
        return tuple((str(row['root_name']), str(row['base_uri'])) for row in rows)

    def list_connections(self) -> tuple[tuple[str, str, str | None], ...]:
        """Return configured shared SQL connections in name order."""
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT connection_name, sqlalchemy_url, credential_ref '
                'FROM connections ORDER BY connection_name'
            ).fetchall()
        return tuple(
            (
                str(row['connection_name']),
                str(row['sqlalchemy_url']),
                row['credential_ref'],
            )
            for row in rows
        )
