"""Typed TOML manifest parsing and semantic validation."""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from difflib import get_close_matches
from pathlib import Path
from types import MappingProxyType

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from .exceptions import DependencyCycleError, ManifestError, VersionOverlapError
from .models import DatasetId

SOURCE_TYPES = frozenset(
    {
        'sql_table',
        'sql_query',
        'csv',
        'parquet',
        'sas7bdat',
    }
)
_ROOT_FIELDS = frozenset({'etlonomy_manifest', 'datasets'})
_DATASET_FIELDS = frozenset({'canonical_name', 'description', 'versions'})
_VERSION_FIELDS = frozenset(
    {
        'version',
        'valid_from',
        'valid_to',
        'source_type',
        'source_uri',
        'source_root',
        'connection',
        'credential_ref',
        'query',
        'options',
        'description',
        'dependencies',
        'columns',
    }
)
_COLUMN_FIELDS = frozenset({'source', 'data_type', 'nullable', 'description'})
_SQL_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')


@dataclass(frozen=True, slots=True)
class ColumnManifest:
    """Describe optional metadata for one logical column."""

    logical_name: str
    source_name: str | None = None
    data_type: str | None = None
    nullable: bool | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetVersionManifest:
    """Describe one temporally valid physical dataset implementation."""

    version: int
    valid_from: date
    valid_to: date | None
    source_type: str
    source_uri: str | None = None
    source_root: str | None = None
    connection: str | None = None
    credential_ref: str | None = None
    query: str | None = None
    options: Mapping[str, object] = field(default_factory=dict)
    description: str | None = None
    dependencies: tuple[DatasetId, ...] = ()
    columns: tuple[ColumnManifest, ...] = ()

    def __post_init__(self):
        """Protect source options from mutation after manifest validation."""
        object.__setattr__(self, 'options', MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Describe a stable logical dataset and all physical versions."""

    dataset: DatasetId
    description: str | None
    versions: tuple[DatasetVersionManifest, ...]


@dataclass(frozen=True, slots=True)
class Manifest:
    """Contain a validated ETLonomy manifest document."""

    schema_version: int
    datasets: tuple[DatasetManifest, ...]


def _date(value, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ManifestError(f'{field_name} must be an ISO date') from error
    raise ManifestError(f'{field_name} must be a TOML date or ISO date string')


def _dataset_id(value, field_name: str) -> DatasetId:
    if not isinstance(value, str):
        raise ManifestError(f'{field_name} must be a string')
    try:
        return DatasetId.parse(value)
    except ValueError as error:
        raise ManifestError(str(error)) from error


def _optional_string(value, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f'{field_name} must be a non-empty string')
    return value


def _reject_unknown_fields(
        value: Mapping[str, object], allowed: frozenset[str], context: str
):
    for field_name in value.keys() - allowed:
        suggestion = get_close_matches(field_name, allowed, n=1)
        hint = f'; did you mean {suggestion[0]!r}?' if suggestion else ''
        raise ManifestError(f'unknown {context} field {field_name!r}{hint}')


def _parse_columns(value) -> tuple[ColumnManifest, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ManifestError('columns must be a table')
    columns: list[ColumnManifest] = []
    for logical_name, raw in value.items():
        if not isinstance(logical_name, str) or not logical_name.strip():
            raise ManifestError('logical column names must be non-empty strings')
        if not isinstance(raw, dict):
            raise ManifestError(f'column {logical_name!r} must be a table')
        _reject_unknown_fields(raw, _COLUMN_FIELDS, f'column {logical_name!r}')
        nullable = raw.get('nullable')
        if nullable is not None and not isinstance(nullable, bool):
            raise ManifestError(f'column {logical_name!r} nullable must be boolean')
        columns.append(
            ColumnManifest(
                logical_name=logical_name,
                source_name=_optional_string(
                    raw.get('source'), f'column {logical_name!r} source'
                ),
                data_type=_optional_string(
                    raw.get('data_type'), f'column {logical_name!r} data_type'
                ),
                nullable=nullable,
                description=_optional_string(
                    raw.get('description'), f'column {logical_name!r} description'
                ),
            )
        )
    return tuple(columns)


def _parse_version(raw, canonical_name: str) -> DatasetVersionManifest:
    if not isinstance(raw, dict):
        raise ManifestError(f'versions for {canonical_name} must be tables')
    _reject_unknown_fields(raw, _VERSION_FIELDS, 'dataset-version')
    try:
        version = raw['version']
        valid_from = _date(raw['valid_from'], 'valid_from')
        source_type = raw['source_type']
    except KeyError as error:
        raise ManifestError(
            f'missing required version field: {error.args[0]}'
        ) from error
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ManifestError('version must be a positive integer')
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        raise ManifestError(f'unsupported source_type: {source_type!r}')
    valid_to_raw = raw.get('valid_to')
    valid_to = _date(valid_to_raw, 'valid_to') if valid_to_raw is not None else None
    if valid_to is not None and valid_to <= valid_from:
        raise ManifestError('valid_to must be later than valid_from')
    dependencies_raw = raw.get('dependencies', [])
    if not isinstance(dependencies_raw, list):
        raise ManifestError('dependencies must be an array')
    query = _optional_string(raw.get('query'), 'query')
    if source_type in {'sql_table', 'sql_query'} and not query:
        raise ManifestError(f'{source_type} requires query')
    options = raw.get('options', {})
    if not isinstance(options, dict):
        raise ManifestError('options must be a table')
    columns = _parse_columns(raw.get('columns'))
    source_uri = _optional_string(raw.get('source_uri'), 'source_uri')
    source_root = _optional_string(raw.get('source_root'), 'source_root')
    connection = _optional_string(raw.get('connection'), 'connection')
    if source_type in {'csv', 'parquet', 'sas7bdat'}:
        if source_uri is None:
            raise ManifestError(f'{source_type} requires source_uri')
        if connection is not None:
            raise ManifestError(f'{source_type} source cannot declare connection')
    else:
        if source_root is not None:
            raise ManifestError(f'{source_type} source cannot declare source_root')
        if (source_uri is None) == (connection is None):
            raise ManifestError(
                f'{source_type} requires exactly one of source_uri or connection'
            )
        if source_uri is not None:
            _validate_sqlalchemy_url(source_uri, 'source_uri')
        if source_type == 'sql_table' and query is not None:
            _validate_table_reference(query)
    credential_ref = raw.get('credential_ref')
    if credential_ref is not None and (
            not isinstance(credential_ref, str) or not credential_ref.strip()
    ):
        raise ManifestError('credential_ref must be a non-empty string')
    return DatasetVersionManifest(
        version=version,
        valid_from=valid_from,
        valid_to=valid_to,
        source_type=source_type,
        source_uri=source_uri,
        source_root=source_root,
        connection=connection,
        credential_ref=credential_ref,
        query=query,
        options=options,
        description=_optional_string(raw.get('description'), 'version description'),
        dependencies=tuple(
            _dataset_id(item, 'dependency') for item in dependencies_raw
        ),
        columns=columns,
    )


def _validate_sqlalchemy_url(value: str, field_name: str):
    try:
        make_url(value)
    except (ArgumentError, TypeError, ValueError) as error:
        raise ManifestError(f'{field_name} must be a valid SQLAlchemy URL') from error


def _validate_table_reference(value: str):
    parts = value.split('.')
    if not parts or any(not _SQL_IDENTIFIER.fullmatch(part) for part in parts):
        raise ManifestError(f'invalid SQL table reference: {value!r}')


def _validate_intervals(
        dataset: DatasetId, versions: tuple[DatasetVersionManifest, ...]
):
    for previous, current in zip(versions, versions[1:], strict=False):
        if previous.valid_to is None or current.valid_from < previous.valid_to:
            raise VersionOverlapError(
                f'versions {previous.version} and {current.version} overlap for {dataset}'
            )


def _parse_manifest(data: bytes, *, validate_dependencies: bool) -> Manifest:
    try:
        raw = tomllib.loads(data.decode('utf8'))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ManifestError(f'invalid TOML manifest: {error}') from error
    if raw.get('etlonomy_manifest') != 1:
        raise ManifestError('etlonomy_manifest must equal 1')
    _reject_unknown_fields(raw, _ROOT_FIELDS, 'manifest')
    raw_datasets = raw.get('datasets')
    if not isinstance(raw_datasets, list):
        raise ManifestError('datasets must be an array of tables')
    datasets: list[DatasetManifest] = []
    seen: set[DatasetId] = set()
    for raw_dataset in raw_datasets:
        if not isinstance(raw_dataset, dict):
            raise ManifestError('each dataset must be a table')
        _reject_unknown_fields(raw_dataset, _DATASET_FIELDS, 'dataset')
        dataset = _dataset_id(raw_dataset.get('canonical_name'), 'canonical_name')
        if dataset in seen:
            raise ManifestError(f'duplicate dataset: {dataset}')
        seen.add(dataset)
        raw_versions = raw_dataset.get('versions')
        if not isinstance(raw_versions, list) or not raw_versions:
            raise ManifestError(f'{dataset} must define at least one version')
        versions = tuple(
            sorted(
                (_parse_version(item, str(dataset)) for item in raw_versions),
                key=lambda item: item.valid_from,
            )
        )
        version_numbers = [item.version for item in versions]
        if len(set(version_numbers)) != len(version_numbers):
            raise ManifestError(f'duplicate version for {dataset}')
        _validate_intervals(dataset, versions)
        datasets.append(
            DatasetManifest(
                dataset,
                _optional_string(raw_dataset.get('description'), 'dataset description'),
                versions,
            )
        )
    if validate_dependencies:
        _validate_dependencies(tuple(datasets))
    return Manifest(1, tuple(sorted(datasets, key=lambda item: str(item.dataset))))


def _validate_dependencies(datasets: tuple[DatasetManifest, ...]):
    known = {dataset.dataset for dataset in datasets}
    for dataset in datasets:
        for version in dataset.versions:
            if len(set(version.dependencies)) != len(version.dependencies):
                raise ManifestError(f'duplicate dependency for {dataset.dataset}')
            unknown = set(version.dependencies) - known
            if unknown:
                names = ', '.join(sorted(map(str, unknown)))
                raise ManifestError(
                    f'unknown dependencies for {dataset.dataset}: {names}'
                )
    _validate_dependency_cycles(datasets)


def _validate_dependency_cycles(datasets: tuple[DatasetManifest, ...]):
    boundaries = sorted(
        {
            boundary
            for dataset in datasets
            for version in dataset.versions
            for boundary in (version.valid_from, version.valid_to)
            if boundary is not None
        }
    )
    for boundary in boundaries:
        graph: dict[DatasetId, tuple[DatasetId, ...]] = {}
        for dataset in datasets:
            active = next(
                (
                    version
                    for version in dataset.versions
                    if version.valid_from <= boundary
                       and (version.valid_to is None or boundary < version.valid_to)
                ),
                None,
            )
            if active is not None:
                graph[dataset.dataset] = active.dependencies
        _assert_dependency_graph_acyclic(graph, boundary)


def _assert_dependency_graph_acyclic(graph: Mapping[DatasetId, tuple[DatasetId, ...]], boundary: date):
    visiting: set[DatasetId] = set()
    visited: set[DatasetId] = set()

    def visit(dataset: DatasetId):
        if dataset in visiting:
            raise DependencyCycleError(
                f'dataset dependency cycle includes {dataset} on {boundary}'
            )
        if dataset in visited:
            return
        visiting.add(dataset)
        for dependency in graph.get(dataset, ()):
            if dependency in graph:
                visit(dependency)
        visiting.remove(dataset)
        visited.add(dataset)

    for dataset in graph:
        visit(dataset)


def parse_manifest(data: bytes) -> Manifest:
    """Parse and validate one TOML manifest document."""
    return _parse_manifest(data, validate_dependencies=True)


def load_manifest(path: Path) -> Manifest:
    """Load and validate one TOML manifest file."""
    try:
        return parse_manifest(path.read_bytes())
    except OSError as error:
        raise ManifestError(f'cannot read manifest {path}: {error}') from error


def load_manifest_directory(path: Path) -> Manifest:
    """Load all TOML files in a directory into one validated manifest."""
    files = sorted(path.glob('*.toml'))
    if not files:
        raise ManifestError(f'no TOML manifests found in {path}')
    try:
        manifests = [
            _parse_manifest(file.read_bytes(), validate_dependencies=False)
            for file in files
        ]
    except OSError as error:
        raise ManifestError(
            f'cannot read manifest directory {path}: {error}'
        ) from error
    combined = tuple(dataset for manifest in manifests for dataset in manifest.datasets)
    names = [dataset.dataset for dataset in combined]
    if len(set(names)) != len(names):
        raise ManifestError('duplicate dataset across manifest files')
    _validate_dependencies(combined)
    return Manifest(1, tuple(sorted(combined, key=lambda item: str(item.dataset))))
