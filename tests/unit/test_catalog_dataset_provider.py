"""Tests for catalog resolution and adapter dispatch."""

from dataclasses import dataclass
from datetime import date

import polars as pl
import pytest

from etlonomy.adapters import AdapterSource
from etlonomy.catalog_provider import CatalogDatasetProvider
from etlonomy.exceptions import CatalogEnvironmentMismatchError, DatasetProviderError
from etlonomy.models import DatasetId, ExecutionContext, Read


@dataclass
class RecordingAdapter:
    """Record provider dispatch arguments."""

    call: tuple[AdapterSource, tuple[str, ...]] | None = None

    def read(self, source, columns):
        self.call = (source, columns)
        return pl.DataFrame({'person_id': [1]}).lazy()


class RecordingCatalog:
    """Resolve one dictionary-backed catalog version."""

    call = None

    def resolve_dataset(self, dataset, *, as_of, version):
        self.call = (dataset, as_of, version)
        return {
            'source_type': 'csv',
            'source_uri': 'claims.csv',
            'options_json': '{"separator": "|"}',
            'columns': {'person_id': {'source': 'member_id'}},
        }


def test_catalog_provider_resolves_context_version_and_dispatches_mapping():
    catalog = RecordingCatalog()
    adapter = RecordingAdapter()
    provider = CatalogDatasetProvider(catalog, adapters={'csv': adapter})
    dataset = DatasetId('CLAIMS', 'CLAIM_LINE')
    context = ExecutionContext(as_of=date(2026, 8, 20))

    result = provider.read(Read(dataset, ('person_id',), 2), context)

    assert result.collect().height == 1
    assert catalog.call == (dataset, context.as_of, 2)
    assert adapter.call == (
        AdapterSource(
            'csv',
            'claims.csv',
            options={'separator': '|'},
            columns={'person_id': 'member_id'},
        ),
        ('person_id',),
    )


def test_explicit_environment_requires_resolver_environment_identity():
    provider = CatalogDatasetProvider(
        RecordingCatalog(), adapters={'csv': RecordingAdapter()}
    )

    with pytest.raises(
            CatalogEnvironmentMismatchError, match='does not expose an environment'
    ):
        provider.read(
            Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('person_id',)),
            ExecutionContext('prod', date(2026, 8, 20)),
        )


def test_catalog_provider_treats_column_mappings_as_partial_metadata():
    adapter = RecordingAdapter()
    provider = CatalogDatasetProvider(RecordingCatalog(), adapters={'csv': adapter})

    provider.read(
        Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('person_id', 'unchanged')),
        ExecutionContext(as_of=date(2026, 1, 1)),
    )

    assert adapter.call is not None
    assert adapter.call[0].columns == {'person_id': 'member_id'}
    assert adapter.call[1] == ('person_id', 'unchanged')


def test_catalog_provider_rejects_unsupported_source_type():
    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return {'source_type': 'future'}

    provider = CatalogDatasetProvider(Catalog())
    with pytest.raises(DatasetProviderError, match='Unsupported source type'):
        provider.read(
            Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('id',)),
            ExecutionContext(as_of=date(2026, 1, 1)),
        )


def test_catalog_provider_rejects_invalid_options_json():
    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return {
                'source_type': 'csv',
                'source_uri': 'claims.csv',
                'options_json': 'not-json',
            }

    provider = CatalogDatasetProvider(Catalog())
    with pytest.raises(DatasetProviderError, match='invalid source options'):
        provider.read(
            Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('id',)),
            ExecutionContext(as_of=date(2026, 1, 1)),
        )


def test_catalog_provider_rejects_missing_source_type():
    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return object()

    provider = CatalogDatasetProvider(Catalog())
    with pytest.raises(DatasetProviderError, match='no valid source type'):
        provider.read(
            Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('id',)),
            ExecutionContext(as_of=date(2026, 1, 1)),
        )


def test_catalog_provider_accepts_mapping_options_without_json_decoding():
    adapter = RecordingAdapter()

    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return {
                'source_type': 'csv',
                'source_uri': 'claims.csv',
                'options': {'has_header': True},
            }

    provider = CatalogDatasetProvider(Catalog(), adapters={'csv': adapter})
    provider.read(
        Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('id',)),
        ExecutionContext(as_of=date(2026, 1, 1)),
    )

    assert adapter.call is not None
    assert adapter.call[0].options == {'has_header': True}


def test_catalog_provider_rejects_non_object_options_json():
    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return {
                'source_type': 'csv',
                'source_uri': 'claims.csv',
                'options_json': '[]',
            }

    provider = CatalogDatasetProvider(Catalog())
    with pytest.raises(DatasetProviderError, match='must be an object'):
        provider.read(
            Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('id',)),
            ExecutionContext(as_of=date(2026, 1, 1)),
        )


def test_catalog_provider_rejects_non_text_options_json():
    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return {
                'source_type': 'csv',
                'source_uri': 'claims.csv',
                'options_json': object(),
            }

    provider = CatalogDatasetProvider(Catalog())
    with pytest.raises(DatasetProviderError, match='invalid source options'):
        provider.read(
            Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('id',)),
            ExecutionContext(as_of=date(2026, 1, 1)),
        )


@dataclass
class ColumnMetadata:
    logical_name: str | None
    source_name: str | None = None
    source: str | None = None


@dataclass
class ObjectResolvedDataset:
    source_type: str = 'csv'
    source_uri: str = 'claims.csv'
    query: str | None = None
    options: object = None
    columns: tuple[ColumnMetadata, ...] = ()


def test_catalog_provider_normalizes_object_column_metadata_variants():
    adapter = RecordingAdapter()
    resolved = ObjectResolvedDataset(
        columns=(
            ColumnMetadata('person_id', source_name='member_id'),
            ColumnMetadata('service_date', source='svc_dt'),
            ColumnMetadata('amount'),
            ColumnMetadata(None),
        )
    )

    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return resolved

    provider = CatalogDatasetProvider(Catalog(), adapters={'csv': adapter})
    provider.read(
        Read(
            DatasetId('CLAIMS', 'CLAIM_LINE'), ('person_id', 'service_date', 'amount')
        ),
        ExecutionContext(as_of=date(2026, 1, 1)),
    )

    assert adapter.call is not None
    assert adapter.call[0].columns == {
        'person_id': 'member_id',
        'service_date': 'svc_dt',
        'amount': 'amount',
    }


def test_catalog_provider_accepts_direct_string_column_mapping():
    adapter = RecordingAdapter()

    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return {
                'source_type': 'csv',
                'source_uri': 'claims.csv',
                'columns': {'person_id': 'member_id'},
            }

    provider = CatalogDatasetProvider(Catalog(), adapters={'csv': adapter})
    provider.read(
        Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('person_id',)),
        ExecutionContext(as_of=date(2026, 1, 1)),
    )

    assert adapter.call is not None
    assert adapter.call[0].columns == {'person_id': 'member_id'}


def test_catalog_provider_passes_shared_connection_credentials_to_adapter():
    adapter = RecordingAdapter()

    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return {
                'source_type': 'sql_table',
                'connection': 'warehouse',
                'query': 'claims',
            }

        def get_connection(self, name):
            assert name == 'warehouse'
            return ('sqlite:///warehouse.db', 'env://?password=DB_PASSWORD')

    provider = CatalogDatasetProvider(Catalog(), adapters={'sql_table': adapter})
    provider.read(
        Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('person_id',)),
        ExecutionContext(),
    )

    assert adapter.call is not None
    assert adapter.call[0].source_uri == 'sqlite:///warehouse.db'
    assert adapter.call[0].credential_ref == 'env://?password=DB_PASSWORD'


@pytest.mark.parametrize(('resolved', 'message'), [
    (
            {'source_type': 'csv', 'source_root': 'files', 'source_uri': 'a.csv'},
            'does not support shared file roots',
    ),
    (
            {'source_type': 'sql_table', 'connection': 'warehouse'},
            'does not support shared SQL connections',
    ),
])
def test_catalog_provider_requires_catalog_support_for_shared_sources(
        resolved, message
):
    class Catalog:
        def resolve_dataset(self, dataset, *, as_of, version):
            return resolved

    provider = CatalogDatasetProvider(Catalog())
    with pytest.raises(DatasetProviderError, match=message):
        provider.read(
            Read(DatasetId('CLAIMS', 'CLAIM_LINE'), ('person_id',)),
            ExecutionContext(),
        )
