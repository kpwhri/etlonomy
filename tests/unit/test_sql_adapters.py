"""Tests for SQL projection and SQLAlchemy connection handling."""

import sqlite3
from contextlib import closing

import polars as pl
import pytest
from sqlalchemy import create_engine

from etlonomy.adapters import AdapterSource, SqlAdapter
from etlonomy.adapters.sql import build_projected_sql
from etlonomy.credentials import MappingCredentialProvider, ResolvedCredential
from etlonomy.exceptions import (
    CredentialProviderNotConfiguredError,
    DatasetProviderError,
)


def test_sql_table_projection_quotes_names_and_applies_physical_mapping():
    source = AdapterSource(
        'sql_table',
        'sqlite:///claims.db',
        'dbo.claim_line',
        columns={'person_id': 'member_id'},
    )

    query = build_projected_sql(source, ('person_id', 'service_date'))

    assert query == (
        'SELECT "member_id" AS "person_id", "service_date" FROM "dbo"."claim_line"'
    )
    assert 'SELECT *' not in query


def test_sql_query_projection_removes_terminal_semicolon():
    source = AdapterSource(
        'sql_query',
        'sqlite:///claims.db',
        ' SELECT member_id AS person_id FROM claims;  ',
    )

    assert build_projected_sql(source, ('person_id',)) == (
        'SELECT "person_id" FROM '
        '(SELECT member_id AS person_id FROM claims) AS etlonomy_source'
    )


@pytest.mark.parametrize(('source', 'message'), [
    (AdapterSource('sql_table', 'sqlite:///x.db'), 'table reference'),
    (AdapterSource('sql_query', 'sqlite:///x.db'), 'requires a query'),
    (AdapterSource('sql_table', 'sqlite:///x.db', 'bad;drop'), 'invalid SQL'),
    (AdapterSource('csv', 'x', 'table'), 'unsupported SQL'),
])
def test_sql_projection_rejects_invalid_source_metadata(source, message):
    with pytest.raises(DatasetProviderError, match=message):
        build_projected_sql(source, ('person_id',))


def test_sql_adapter_reads_real_sqlite_database(tmp_path):
    database = tmp_path / 'claims.db'
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute('CREATE TABLE claims (person_id INTEGER, ignored TEXT)')
            connection.execute("INSERT INTO claims VALUES (1, 'not selected')")

    result = SqlAdapter().read(
        AdapterSource('sql_table', f'sqlite:///{database.as_posix()}', 'claims'),
        ('person_id',),
    )

    assert isinstance(result, pl.LazyFrame)
    assert result.collect().to_dict(as_series=False) == {'person_id': [1]}


def test_sql_adapter_applies_credentials_structurally_without_leaking_secrets():
    recorded = {}
    provider = MappingCredentialProvider(
        {'test://claims': ResolvedCredential(username='alice', password='p@ss/word')}
    )

    def engine_factory(url, **kwargs):
        recorded['url'] = url
        return create_engine('sqlite:///:memory:')

    SqlAdapter(provider, engine_factory=engine_factory).read(
        AdapterSource(
            'sql_query',
            'postgresql://database.example/claims',
            'SELECT 1 AS id',
            credential_ref='test://claims',
        ),
        ('id',),
    )

    url = recorded['url']
    assert url.username == 'alice'
    assert url.password == 'p@ss/word'
    assert 'p@ss/word' not in str(url)


def test_sql_adapter_does_not_call_provider_without_credential_reference(tmp_path):
    class FailingProvider:
        def resolve(self, reference):
            raise AssertionError('credential provider must not be called')

    database = tmp_path / 'claims.db'
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute('CREATE TABLE claims (id INTEGER)')

    SqlAdapter(FailingProvider()).read(
        AdapterSource('sql_table', f'sqlite:///{database.as_posix()}', 'claims'),
        ('id',),
    )


def test_sql_adapter_requires_provider_only_when_reference_is_declared():
    with pytest.raises(CredentialProviderNotConfiguredError):
        SqlAdapter().read(
            AdapterSource(
                'sql_table',
                'sqlite:///:memory:',
                'claims',
                credential_ref='env://?password=DB_PASSWORD',
            ),
            ('id',),
        )


def test_sql_adapter_translates_engine_failure():
    def fail(url, **kwargs):
        raise RuntimeError('database unavailable')

    adapter = SqlAdapter(engine_factory=fail)
    with pytest.raises(DatasetProviderError, match='database unavailable'):
        adapter.read(
            AdapterSource('sql_table', 'sqlite:///:memory:', 'claims'), ('id',)
        )


def test_sql_adapter_requires_sqlalchemy_url():
    with pytest.raises(DatasetProviderError, match='SQLAlchemy connection URL'):
        SqlAdapter().read(AdapterSource('sql_table', None, 'claims'), ('id',))


def test_sql_projection_rejects_empty_multipart_identifier_component():
    with pytest.raises(DatasetProviderError, match='table reference'):
        build_projected_sql(
            AdapterSource('sql_table', 'sqlite:///claims.db', 'dbo..claims'), ('id',)
        )
