"""Tests for external dataset identities, reads, and runtime routing."""

from datetime import date

import polars as pl
import pytest

import etlonomy
from etlonomy.exceptions import ExternalDatasetProviderNotConfiguredError
from etlonomy.models import (
    ExecutionContext,
    ExternalDatasetId,
    ExternalRead,
    external_read,
)
from etlonomy.providers import TestDatasetProvider
from etlonomy.registry import EtlDefinition, Registry
from etlonomy.runtime import Runtime


class RecordingExternalProvider:
    def __init__(self, value: object):
        self.value = value
        self.calls: list[tuple[ExternalRead, ExecutionContext]] = []

    def read(self, request: ExternalRead, context: ExecutionContext) -> object:
        self.calls.append((request, context))
        return self.value


def test_external_dataset_id_has_stable_namespaced_identity():
    dataset = ExternalDatasetId('vdwcore', 'sv.vdw_claims')

    assert dataset.canonical_name == 'vdwcore:sv.vdw_claims'
    assert str(dataset) == 'vdwcore:sv.vdw_claims'
    assert ExternalDatasetId.parse(str(dataset)) == dataset
    assert hash(ExternalDatasetId.parse(str(dataset))) == hash(dataset)


@pytest.mark.parametrize('system', ['', 'VDWCORE', 'vdw core', ' vdwcore'])
def test_external_dataset_id_rejects_invalid_system(system: str):
    with pytest.raises(ValueError, match='external dataset system'):
        ExternalDatasetId(system, 'sv.claims')


@pytest.mark.parametrize('name', ['', ' sv.claims', 'sv.claims '])
def test_external_dataset_id_rejects_invalid_name(name: str):
    with pytest.raises(ValueError, match='external dataset name'):
        ExternalDatasetId('files', name)


def test_external_dataset_id_parse_requires_namespace_separator():
    with pytest.raises(ValueError, match='canonical external dataset'):
        ExternalDatasetId.parse('sv.claims')


def test_external_read_records_requested_columns():
    dataset = ExternalDatasetId('files', 'sv.claims')

    request = external_read(dataset, 'person_id', 'service_date')

    assert request == ExternalRead(dataset, ('person_id', 'service_date'))


@pytest.mark.parametrize(
    ('columns', 'message'),
    [
        ((), 'at least one'),
        (('person_id', ''), 'must not be empty'),
        (('person_id', 'person_id'), 'must be unique'),
    ],
)
def test_external_read_rejects_invalid_columns(
        columns: tuple[str, ...], message: str
):
    dataset = ExternalDatasetId('files', 'sv.claims')

    with pytest.raises(ValueError, match=message):
        ExternalRead(dataset, columns)


def test_runtime_routes_external_read_and_records_dependency():
    request = external_read(
        ExternalDatasetId('files', 'sv.claims'),
        'person_id',
    )
    supplied = pl.DataFrame({'person_id': [1], 'extra': ['kept']})
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.load',
            lambda claims: claims,
            {'claims': request},
            (),
            None,
            None,
        )
    )
    context = ExecutionContext('test', date(2026, 1, 1))
    external_provider = RecordingExternalProvider(supplied)
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': external_provider},
        context=context,
        job_registry=job_registry,
    )

    assert runtime.run('external.load') is supplied
    assert external_provider.calls == [(request, context)]
    assert runtime.last_dependencies == (request,)


def test_explicit_external_etl_argument_skips_provider_and_keeps_columns():
    request = external_read(
        ExternalDatasetId('files', 'sv.claims'),
        'person_id',
    )
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.override',
            lambda claims: claims,
            {'claims': request},
            (),
            None,
            None,
        )
    )
    external_provider = RecordingExternalProvider(object())
    supplied = pl.DataFrame({
        'person_id': [1],
        'extra_test_column': ['preserved'],
    })
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        external_providers={'files': external_provider},
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    assert runtime.run('external.override', claims=supplied) is supplied
    assert supplied.columns == ['person_id', 'extra_test_column']
    assert external_provider.calls == []
    assert runtime.last_dependencies == ()


def test_runtime_reports_missing_external_provider_without_recording_read():
    request = external_read(ExternalDatasetId('missing', 'sv.claims'), 'person_id')
    job_registry = Registry()
    job_registry.register_etl(
        EtlDefinition(
            'external.missing',
            lambda claims: claims,
            {'claims': request},
            (),
            None,
            None,
        )
    )
    runtime = Runtime(
        provider=TestDatasetProvider({}),
        context=ExecutionContext(),
        job_registry=job_registry,
    )

    with pytest.raises(
            ExternalDatasetProviderNotConfiguredError,
            match="system 'missing'",
    ):
        runtime.run('external.missing')

    assert runtime.last_dependencies == ()


def test_explicit_external_argument_is_passed_unchanged(monkeypatch):
    job_registry = Registry()
    monkeypatch.setattr('etlonomy.decorators.registry', job_registry)
    request = external_read(ExternalDatasetId('files', 'sv.claims'), 'person_id')

    @etlonomy.requires(claims=request)
    def use_claims(claims: pl.DataFrame) -> pl.DataFrame:
        return claims

    supplied = pl.DataFrame({
        'person_id': [1],
        'extra_test_column': ['preserved'],
    })

    result = use_claims(claims=supplied)

    assert result is supplied
    assert result.columns == ['person_id', 'extra_test_column']


def test_package_exports_external_dataset_api():
    assert etlonomy.ExternalDatasetId is ExternalDatasetId
    assert etlonomy.ExternalRead is ExternalRead
    assert etlonomy.external_read is external_read
    assert hasattr(etlonomy, 'ExternalDatasetProvider')
