"""Catalog-backed provider that dispatches resolved sources to adapters."""

import json
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import polars as pl

from etlonomy.adapters import (
    AdapterSource,
    CsvAdapter,
    ParquetAdapter,
    SasAdapter,
    SasReader,
    SourceAdapter,
    SqlAdapter,
)
from etlonomy.credentials import CredentialProvider
from etlonomy.exceptions import CatalogEnvironmentMismatchError, DatasetProviderError
from etlonomy.models import DatasetId, ExecutionContext, Read


class CatalogResolver(Protocol):
    """Resolve a logical read to catalog version metadata."""

    def resolve_dataset(
            self,
            dataset: DatasetId,
            as_of: date | None = None,
            version: int | None = None,
    ) -> object:
        """Return metadata for the selected physical dataset version."""
        ...


class CatalogDatasetProvider:
    """Resolve catalog metadata and delegate physical access to source adapters."""

    def __init__(
            self,
            catalog: CatalogResolver,
            *,
            credential_provider: CredentialProvider | None = None,
            sas_reader: SasReader | None = None,
            adapters: Mapping[str, SourceAdapter] | None = None,
    ) -> None:
        """Configure catalog resolution and physical source boundaries."""
        self._catalog = catalog
        if adapters is None:
            sql = SqlAdapter(credential_provider)
            adapters = {
                'csv': CsvAdapter(),
                'parquet': ParquetAdapter(),
                'sas7bdat': SasAdapter(sas_reader),
                'sql_table': sql,
                'sql_query': sql,
            }
        self._adapters = dict(adapters)

    def read(self, request: Read, context: ExecutionContext) -> pl.LazyFrame:
        """Resolve a version, validate metadata, and read requested columns."""
        self._validate_environment(context)
        resolved = self._resolve(request, context)
        source = _normalize_source(resolved, self._catalog)
        try:
            adapter = self._adapters[source.source_type]
        except KeyError as error:
            raise DatasetProviderError(
                f'Unsupported source type: {source.source_type}'
            ) from error
        return adapter.read(source, request.columns)

    def _validate_environment(self, context: ExecutionContext) -> None:
        if context.environment is None:
            return
        getter = getattr(self._catalog, 'get_environment', None)
        if getter is None:
            raise CatalogEnvironmentMismatchError(
                'execution requested environment validation, but the catalog does '
                'not expose an environment identity'
            )
        catalog_environment = getter()
        if catalog_environment is None:
            raise CatalogEnvironmentMismatchError(
                f'execution requested environment {context.environment!r}, but the '
                'catalog has no environment identity'
            )
        if catalog_environment != context.environment:
            raise CatalogEnvironmentMismatchError(
                f'execution environment {context.environment!r} does not match '
                f'catalog environment {catalog_environment!r}'
            )

    def _resolve(self, request: Read, context: ExecutionContext) -> object:
        return self._catalog.resolve_dataset(
            request.dataset,
            as_of=context.as_of,
            version=request.version,
        )


def _normalize_source(resolved: object, catalog: object) -> AdapterSource:
    source_type = _attribute(resolved, 'source_type')
    if not isinstance(source_type, str):
        raise DatasetProviderError('Resolved dataset has no valid source type')
    source_uri = _attribute(resolved, 'source_uri')
    source_root = _attribute(resolved, 'source_root')
    connection = _attribute(resolved, 'connection')
    query = _attribute(resolved, 'query')
    credential_ref = _attribute(resolved, 'credential_ref')
    if isinstance(source_root, str):
        source_uri = _resolve_root(catalog, source_root, source_uri)
    if isinstance(connection, str):
        source_uri, shared_credential = _resolve_connection(catalog, connection)
        if credential_ref is None:
            credential_ref = shared_credential
    options = _options(resolved)
    columns = _column_mappings(resolved)
    return AdapterSource(
        source_type=source_type,
        source_uri=source_uri if isinstance(source_uri, str) else None,
        credential_ref=credential_ref if isinstance(credential_ref, str) else None,
        query=query if isinstance(query, str) else None,
        options=options,
        columns=columns,
    )


def _resolve_root(catalog: object, name: str, source_uri: object) -> str:
    if not isinstance(source_uri, str):
        raise DatasetProviderError(f'file root {name!r} requires a relative source_uri')
    getter = getattr(catalog, 'get_root', None)
    if getter is None:
        raise DatasetProviderError('catalog does not support shared file roots')
    base = _path_from_uri(getter(name))
    relative = Path(source_uri)
    if relative.is_absolute():
        raise DatasetProviderError(
            f'source_uri must be relative when source_root {name!r} is used'
        )
    root = base.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise DatasetProviderError(
            f'source_uri escapes configured source_root {name!r}'
        ) from error
    return str(resolved)


def _path_from_uri(value: object) -> Path:
    if not isinstance(value, str):
        raise DatasetProviderError('catalog contains an invalid file root')
    direct = Path(value)
    if direct.is_absolute():
        return direct
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != 'file':
        raise DatasetProviderError('file root must be a filesystem path or file URI')
    if parsed.scheme == 'file':
        path = url2pathname(unquote(parsed.path))
        if parsed.netloc:
            path = f'//{parsed.netloc}{path}'
        return Path(path)
    return Path(value)


def _resolve_connection(catalog: object, name: str) -> tuple[str, str | None]:
    getter = getattr(catalog, 'get_connection', None)
    if getter is None:
        raise DatasetProviderError('catalog does not support shared SQL connections')
    value = getter(name)
    if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not isinstance(value[0], str)
            or (value[1] is not None and not isinstance(value[1], str))
    ):
        raise DatasetProviderError('catalog contains an invalid SQL connection')
    return value


def _options(resolved: object) -> Mapping[str, object]:
    value = _attribute(resolved, 'options', None)
    if isinstance(value, Mapping):
        return value
    encoded = _attribute(resolved, 'options_json', None)
    if not encoded:
        return {}
    if not isinstance(encoded, (str, bytes, bytearray)):
        raise DatasetProviderError('Catalog contains invalid source options')
    try:
        decoded = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as error:
        raise DatasetProviderError('Catalog contains invalid source options') from error
    if not isinstance(decoded, dict):
        raise DatasetProviderError('Catalog source options must be an object')
    return decoded


def _column_mappings(resolved: object) -> dict[str, str]:
    value = _attribute(resolved, 'columns', {})
    if isinstance(value, Mapping):
        return {
            str(logical): _source_name(metadata, str(logical))
            for logical, metadata in value.items()
        }
    mappings: dict[str, str] = {}
    for metadata in cast(Iterable[object], value or ()):
        logical = _attribute(metadata, 'logical_name')
        if isinstance(logical, str):
            mappings[logical] = _source_name(metadata, logical)
    return mappings


def _source_name(metadata: object, default: str) -> str:
    if isinstance(metadata, str):
        return metadata
    value = _attribute(metadata, 'source_name', None)
    if value is None:
        value = _attribute(metadata, 'source', None)
    return value if isinstance(value, str) and value else default


def _attribute(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)
