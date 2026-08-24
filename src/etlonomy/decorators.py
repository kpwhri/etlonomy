"""Decorators for declaring ETL jobs and reusable dataset requirements."""

import inspect
import re
from collections.abc import Callable, Mapping
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar, cast

from etlonomy.exceptions import RegistryError
from etlonomy.models import DatasetId, Read
from etlonomy.registry import EtlDefinition, RequirementDefinition, registry

P = ParamSpec('P')
R = TypeVar('R')
_ETL_NAME = re.compile(r'^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$')


def _source(function: Callable[..., object]) -> tuple[Path | None, int | None]:
    try:
        path = inspect.getsourcefile(function)
        _, line = inspect.getsourcelines(function)
    except (OSError, TypeError):
        return None, None
    return Path(path) if path else None, line


def _validate_inputs(
        function: Callable[..., object], inputs: Mapping[str, Read]
) -> None:
    parameters = inspect.signature(function).parameters
    missing = sorted(set(inputs) - set(parameters))
    if missing:
        names = ', '.join(missing)
        raise RegistryError(
            f'declared inputs are not function parameters for '
            f'{function.__qualname__}: {names}'
        )


def etl(
        *,
        name: str,
        inputs: Mapping[str, Read],
        outputs: tuple[DatasetId, ...] = (),
        uses: tuple[Callable[..., object], ...] = (),
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Declare and register a top-level ETL job."""
    if not _ETL_NAME.fullmatch(name):
        raise RegistryError('ETL job names must be dotted lowercase names')

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        if getattr(function, '__etlonomy_requirement__', False):
            raise RegistryError('a function cannot use both etl and requires')
        _validate_inputs(function, inputs)
        source_file, source_line = _source(function)
        definition = EtlDefinition(
            name=name,
            function=cast(Callable[..., object], function),
            inputs=dict(inputs),
            outputs=tuple(outputs),
            source_file=source_file,
            source_line=source_line,
            uses=tuple(uses),
        )
        registry.register_etl(definition)
        object.__setattr__(function, '__etlonomy_etl__', True)
        return function

    return decorate


def requires(
        *,
        uses: tuple[Callable[..., object], ...] = (),
        **inputs: Read,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Declare datasets that an active runtime injects into a reusable function.

    Explicitly passed arguments always take precedence over runtime resolution.
    """

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        if getattr(function, '__etlonomy_etl__', False):
            raise RegistryError('a function cannot use both etl and requires')
        _validate_inputs(function, inputs)
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = signature.bind_partial(*args, **kwargs)
            unresolved = {
                name: request
                for name, request in inputs.items()
                if name not in bound.arguments
            }
            if unresolved:
                from etlonomy.runtime import get_active_runtime

                runtime = get_active_runtime()
                kwargs.update(runtime.resolve_inputs(unresolved))
            return function(*args, **kwargs)

        object.__setattr__(wrapped, '__etlonomy_requirement__', True)
        source_file, source_line = _source(function)
        registry.register_requirement(
            RequirementDefinition(
                function=cast(Callable[..., object], wrapped),
                inputs=dict(inputs),
                source_file=source_file,
                source_line=source_line,
                uses=tuple(uses),
            )
        )
        return wrapped

    return decorate
