"""Registration metadata for ETL jobs and reusable requirements."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from etlonomy.exceptions import RegistryError
from etlonomy.models import DatasetId, DependencyRead
from etlonomy.providers import ExternalProviderBinding


@dataclass(frozen=True, slots=True)
class EtlDefinition:
    """Describe a registered top-level ETL job and its declared data contract."""

    name: str
    function: Callable[..., object]
    inputs: Mapping[str, DependencyRead]
    outputs: tuple[DatasetId, ...]
    source_file: Path | None
    source_line: int | None
    uses: tuple[Callable[..., object], ...] = ()

    def __post_init__(self):
        """Protect registered inputs and sequences from later mutation."""
        object.__setattr__(self, 'inputs', MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, 'outputs', tuple(self.outputs))
        object.__setattr__(self, 'uses', tuple(self.uses))


@dataclass(frozen=True, slots=True)
class RequirementDefinition:
    """Describe the datasets injected into a reusable function."""

    function: Callable[..., object]
    inputs: Mapping[str, DependencyRead]
    source_file: Path | None
    source_line: int | None
    uses: tuple[Callable[..., object], ...] = ()
    external_provider_bindings: Mapping[str, ExternalProviderBinding] = field(
        default_factory=dict
    )

    def __post_init__(self):
        """Protect registered requirement metadata from later mutation."""
        object.__setattr__(self, 'inputs', MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, 'uses', tuple(self.uses))
        object.__setattr__(
            self,
            'external_provider_bindings',
            MappingProxyType(dict(self.external_provider_bindings)),
        )


class Registry:
    """Store ETL and reusable-function definitions for execution and inspection."""

    def __init__(self):
        """Create an empty ETL and requirement registry."""
        self._etls: dict[str, EtlDefinition] = {}
        self._requirements: dict[Callable[..., object], RequirementDefinition] = {}

    def register_etl(self, definition: EtlDefinition):
        """Register an ETL definition, rejecting duplicate job names."""
        if definition.name in self._etls:
            raise RegistryError(f'ETL job {definition.name!r} is already registered')
        self._validate_uses(definition.uses, f'ETL job {definition.name!r}')
        self._etls[definition.name] = definition

    def register_requirement(self, definition: RequirementDefinition):
        """Register dependency metadata for one reusable function."""
        if definition.function in self._requirements:
            function_name = definition.function.__qualname__
            raise RegistryError(f'function {function_name!r} already has requirements')
        if definition.function in definition.uses:
            raise RegistryError(
                f'function {definition.function.__qualname__!r} cannot use itself'
            )
        self._validate_uses(
            definition.uses, f'function {definition.function.__qualname__!r}'
        )
        self._requirements[definition.function] = definition
        try:
            self._validate_requirement_cycles()
        except RegistryError:
            self._requirements.pop(definition.function)
            raise

    def _validate_uses(self, uses: tuple[Callable[..., object], ...], owner: str):
        if len(set(uses)) != len(uses):
            raise RegistryError(f'{owner} contains duplicate uses declarations')
        for function in uses:
            if not callable(function):
                raise RegistryError(f'{owner} uses a value that is not callable')
            if function not in self._requirements:
                name = getattr(function, '__qualname__', repr(function))
                raise RegistryError(
                    f'{owner} uses {name!r}, which is not registered with requires'
                )

    def _validate_requirement_cycles(self):
        visiting: set[Callable[..., object]] = set()
        visited: set[Callable[..., object]] = set()

        def visit(function: Callable[..., object]):
            if function in visiting:
                raise RegistryError(
                    f'reusable-function uses cycle includes {function.__qualname__!r}'
                )
            if function in visited:
                return
            visiting.add(function)
            for used in self._requirements[function].uses:
                visit(used)
            visiting.remove(function)
            visited.add(function)

        for function in self._requirements:
            visit(function)

    def get_etl(self, name: str) -> EtlDefinition:
        """Return a named ETL definition.

        Raises:
            RegistryError: If the job has not been registered.

        """
        try:
            return self._etls[name]
        except KeyError as error:
            raise RegistryError(f'ETL job {name!r} is not registered') from error

    def get_requirement(self, function: Callable[..., object]) -> RequirementDefinition:
        """Return requirement metadata for a decorated function."""
        try:
            return self._requirements[function]
        except KeyError as error:
            raise RegistryError(
                f'function {function.__qualname__!r} has no registered requirements'
            ) from error

    @property
    def etls(self) -> tuple[EtlDefinition, ...]:
        """Return ETL definitions ordered deterministically by job name."""
        return tuple(self._etls[name] for name in sorted(self._etls))

    @property
    def requirements(self) -> tuple[RequirementDefinition, ...]:
        """Return requirement definitions in deterministic source order."""
        return tuple(
            sorted(
                self._requirements.values(),
                key=lambda item: (
                    str(item.source_file or ''),
                    item.source_line or 0,
                    item.function.__qualname__,
                ),
            )
        )


registry = Registry()
