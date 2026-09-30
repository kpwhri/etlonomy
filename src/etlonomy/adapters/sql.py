"""SQLAlchemy-backed adapters with source-side projection."""

import re
from collections.abc import Callable

import polars as pl
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine, make_url

from etlonomy.adapters.base import AdapterSource
from etlonomy.credentials import CredentialProvider, ResolvedCredential
from etlonomy.exceptions import (
    CredentialProviderNotConfiguredError,
    DatasetProviderError,
)

EngineFactory = Callable[..., Engine]
IdentifierQuoter = Callable[[str], str]
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')


class SqlAdapter:
    """Read SQL tables or queries from dataset-owned SQLAlchemy URLs."""

    def __init__(
            self,
            credential_provider: CredentialProvider | None = None,
            *,
            engine_factory: EngineFactory = create_engine,
    ) :
        """Configure optional credential lookup and an injectable engine boundary."""
        self._credential_provider = credential_provider
        self._engine_factory = engine_factory

    def read(self, source: AdapterSource, columns: tuple[str, ...]) -> pl.LazyFrame:
        """Execute a projected SQL read and return the result as a lazy frame."""
        url, connect_args = self._connection_settings(source)
        engine: Engine | None = None
        try:
            engine = self._engine_factory(url, connect_args=connect_args)
            query = build_projected_sql(
                source,
                columns,
                quote_identifier=engine.dialect.identifier_preparer.quote_identifier,
            )
            with engine.connect() as connection:
                return pl.read_database(query, connection).lazy()
        except Exception as error:
            raise DatasetProviderError(
                f'unable to read {source.source_type} source: {error}'
            ) from error
        finally:
            if engine is not None:
                engine.dispose()

    def _connection_settings(
            self, source: AdapterSource
    ) -> tuple[URL, dict[str, object]]:
        if not source.source_uri:
            raise DatasetProviderError(
                f'{source.source_type} source requires a SQLAlchemy connection URL'
            )
        try:
            url = make_url(source.source_uri)
        except Exception as error:
            raise DatasetProviderError(
                'source_uri is not a valid SQLAlchemy URL'
            ) from error
        if source.credential_ref is None:
            return url, {}
        if self._credential_provider is None:
            raise CredentialProviderNotConfiguredError(
                'dataset declares credential_ref but no credential provider is configured'
            )
        credential = self._credential_provider.resolve(source.credential_ref)
        return _apply_credential(url, credential)


def _apply_credential(
        url: URL, credential: ResolvedCredential
) -> tuple[URL, dict[str, object]]:
    updated = url.set(
        username=credential.username
        if credential.username is not None
        else url.username,
        password=credential.password
        if credential.password is not None
        else url.password,
    )
    connect_args = dict(credential.options)
    if credential.token is not None:
        connect_args.setdefault('access_token', credential.token)
    return updated, connect_args


def build_projected_sql(
        source: AdapterSource,
        columns: tuple[str, ...],
        *,
        quote_identifier: IdentifierQuoter | None = None,
) -> str:
    """Build SQL that selects only requested physical columns.

    Runtime reads supply the active SQLAlchemy dialect's identifier quoter. Direct
    callers receive portable ANSI double-quoted identifiers.
    """
    quote = quote_identifier or _ansi_identifier
    projection = ', '.join(
        _projection(column, source.columns.get(column, column), quote)
        for column in columns
    )
    if source.source_type == 'sql_table':
        if not source.query:
            raise DatasetProviderError(
                f'{source.source_type} source requires a table reference'
            )
        return f'SELECT {projection} FROM {_multipart_identifier(source.query, quote)}'
    if source.source_type == 'sql_query':
        if not source.query or not source.query.strip():
            raise DatasetProviderError(f'{source.source_type} source requires a query')
        stored_query = source.query.strip().rstrip(';').rstrip()
        return f'SELECT {projection} FROM ({stored_query}) AS etlonomy_source'
    raise DatasetProviderError(f'unsupported SQL source type: {source.source_type}')


def _projection(logical: str, physical: str, quote: IdentifierQuoter) -> str:
    selected = _identifier(physical, quote)
    if logical == physical:
        return selected
    return f'{selected} AS {_identifier(logical, quote)}'


def _identifier(value: str, quote: IdentifierQuoter) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise DatasetProviderError(f'invalid SQL identifier: {value}')
    return quote(value)


def _multipart_identifier(value: str, quote: IdentifierQuoter) -> str:
    parts = value.split('.')
    if not parts or any(not part for part in parts):
        raise DatasetProviderError(f'invalid SQL table reference: {value}')
    return '.'.join(_identifier(part, quote) for part in parts)


def _ansi_identifier(value: str) -> str:
    return f'"{value}"'
