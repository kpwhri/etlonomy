"""Tests for ETL runtime execution and argument injection."""

from contextvars import Context
from datetime import date

import polars as pl
import pytest

from etlonomy.exceptions import RegistryError
from etlonomy.models import DatasetId, ExecutionContext, read
from etlonomy.registry import EtlDefinition, Registry
from etlonomy.runtime import Runtime, get_active_runtime


class RecordingProvider:
    def __init__(self):
        self.calls: list[tuple[object, ExecutionContext]] = []

    def read(self, request, context: ExecutionContext) -> pl.LazyFrame:
        self.calls.append((request, context))
        return pl.DataFrame({'value': [3]}).lazy()


def test_runtime_injects_multiple_inputs_and_returns_function_result():
    job_registry = Registry()
    left = read(DatasetId('AREA', 'LEFT'), 'value')
    right = read(DatasetId('AREA', 'RIGHT'), 'value')

    def combine(first: pl.LazyFrame, second: pl.LazyFrame) -> int:
        return first.collect()['value'][0] + second.collect()['value'][0]

    job_registry.register_etl(
        EtlDefinition(
            'area.combine', combine, {'first': left, 'second': right}, (), None, None
        )
    )
    context = ExecutionContext('test', date(2026, 1, 1))
    provider = RecordingProvider()

    runtime = Runtime(provider=provider, context=context, job_registry=job_registry)
    assert runtime.run('area.combine') == 6
    assert [call[0] for call in provider.calls] == [left, right]
    assert all(call[1] is context for call in provider.calls)


def test_runtime_explicit_etl_argument_skips_provider_resolution():
    job_registry = Registry()
    request = read(DatasetId('AREA', 'VALUES'), 'value')
    job_registry.register_etl(
        EtlDefinition(
            'area.value', lambda frame: frame, {'frame': request}, (), None, None
        )
    )
    provider = RecordingProvider()
    explicit = pl.DataFrame({'value': [9]}).lazy()
    runtime = Runtime(
        provider=provider,
        context=ExecutionContext('test', date(2026, 1, 1)),
        job_registry=job_registry,
    )

    assert runtime.run('area.value', frame=explicit) is explicit
    assert provider.calls == []
    assert runtime.last_dependencies == ()


def test_resolve_inputs_outside_job_does_not_create_execution_trace():
    provider = RecordingProvider()
    runtime = Runtime(
        provider=provider,
        context=ExecutionContext('test', date(2026, 1, 1)),
        job_registry=Registry(),
    )
    request = read(DatasetId('AREA', 'VALUES'), 'value')

    resolved = runtime.resolve_inputs({'frame': request})

    assert resolved['frame'].collect()['value'].to_list() == [3]
    assert runtime.last_dependencies == ()


def test_runtime_propagates_job_exception_and_clears_active_context():
    job_registry = Registry()

    def fail():
        raise ValueError('job failed')

    job_registry.register_etl(EtlDefinition('area.fail', fail, {}, (), None, None))
    runtime = Runtime(
        provider=RecordingProvider(),
        context=ExecutionContext('test', date(2026, 1, 1)),
        job_registry=job_registry,
    )

    with pytest.raises(ValueError, match='job failed'):
        runtime.run('area.fail')
    with pytest.raises(RegistryError, match='active Runtime'):
        get_active_runtime()


def test_failed_job_preserves_last_successful_dependency_trace():
    job_registry = Registry()
    request = read(DatasetId('AREA', 'VALUES'), 'value')
    job_registry.register_etl(
        EtlDefinition(
            'area.success', lambda frame: frame, {'frame': request}, (), None, None
        )
    )

    def fail(frame: pl.LazyFrame):
        del frame
        raise ValueError('job failed')

    job_registry.register_etl(
        EtlDefinition('area.fail', fail, {'frame': request}, (), None, None)
    )
    runtime = Runtime(
        provider=RecordingProvider(),
        context=ExecutionContext('test', date(2026, 1, 1)),
        job_registry=job_registry,
    )

    runtime.run('area.success')
    successful_trace = runtime.last_dependencies
    with pytest.raises(ValueError, match='job failed'):
        runtime.run('area.fail')

    assert runtime.last_dependencies == successful_trace == (request,)


def test_dependency_traces_are_isolated_between_execution_contexts():
    job_registry = Registry()
    left = read(DatasetId('AREA', 'LEFT'), 'value')
    right = read(DatasetId('AREA', 'RIGHT'), 'value')
    job_registry.register_etl(
        EtlDefinition('area.left', lambda frame: frame, {'frame': left}, (), None, None)
    )
    job_registry.register_etl(
        EtlDefinition(
            'area.right', lambda frame: frame, {'frame': right}, (), None, None
        )
    )
    runtime = Runtime(
        provider=RecordingProvider(),
        context=ExecutionContext('test', date(2026, 1, 1)),
        job_registry=job_registry,
    )
    left_context = Context()
    right_context = Context()

    left_context.run(runtime.run, 'area.left')
    right_context.run(runtime.run, 'area.right')

    assert left_context.run(lambda: runtime.last_dependencies) == (left,)
    assert right_context.run(lambda: runtime.last_dependencies) == (right,)
    assert runtime.last_dependencies == ()
