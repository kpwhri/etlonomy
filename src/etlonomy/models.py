"""Core immutable values used by ETLonomy public APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_CANONICAL_COMPONENT = re.compile(r'^[A-Z][A-Z0-9_]*$')
_EXTERNAL_SYSTEM = re.compile(r'^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*$')


@dataclass(frozen=True, slots=True)
class DatasetId:
    """Identify a logical dataset independently of its physical source."""

    subject: str
    name: str

    def __post_init__(self) -> None:
        """Validate the canonical subject and dataset components."""
        if not _CANONICAL_COMPONENT.fullmatch(self.subject):
            raise ValueError(f'invalid dataset subject: {self.subject!r}')
        if not _CANONICAL_COMPONENT.fullmatch(self.name):
            raise ValueError(f'invalid dataset name: {self.name!r}')

    @property
    def canonical_name(self) -> str:
        """Return the canonical SUBJECT.DATASET representation."""
        return f'{self.subject}.{self.name}'

    @classmethod
    def parse(cls, canonical_name: str) -> DatasetId:
        """Create an identifier from a canonical SUBJECT.DATASET name."""
        parts = canonical_name.split('.')
        if len(parts) != 2:
            raise ValueError(f'invalid canonical dataset name: {canonical_name!r}')
        return cls(*parts)

    def __str__(self) -> str:
        """Return the canonical dataset name."""
        return self.canonical_name


@dataclass(frozen=True, slots=True)
class ExternalDatasetId:
    """Identify a dataset managed by a system outside Etlonomy."""

    system: str
    name: str

    def __post_init__(self) -> None:
        """Validate the external system and dataset names."""
        if not _EXTERNAL_SYSTEM.fullmatch(self.system):
            raise ValueError(f'invalid external dataset system: {self.system!r}')
        if not self.name or self.name != self.name.strip():
            raise ValueError(f'invalid external dataset name: {self.name!r}')

    @property
    def canonical_name(self) -> str:
        """Return the namespaced SYSTEM:NAME representation."""
        return f'{self.system}:{self.name}'

    @classmethod
    def parse(cls, canonical_name: str) -> ExternalDatasetId:
        """Create an identifier from a namespaced SYSTEM:NAME value."""
        parts = canonical_name.split(':', maxsplit=1)
        if len(parts) != 2:
            raise ValueError(
                f'invalid canonical external dataset name: {canonical_name!r}'
            )
        return cls(*parts)

    def __str__(self) -> str:
        """Return the canonical external dataset name."""
        return self.canonical_name


@dataclass(frozen=True, slots=True)
class Read:
    """Describe the logical columns requested from a dataset."""

    dataset: DatasetId
    columns: tuple[str, ...]
    version: int | None = None

    def __post_init__(self) -> None:
        """Reject empty, duplicate, or invalid read arguments."""
        if not self.columns:
            raise ValueError('at least one column must be requested')
        if any(not column for column in self.columns):
            raise ValueError('requested column names must not be empty')
        if len(set(self.columns)) != len(self.columns):
            raise ValueError('requested columns must be unique')
        if self.version is not None and (
                isinstance(self.version, bool)
                or not isinstance(self.version, int)
                or self.version < 1
        ):
            raise ValueError('version must be a positive integer')


@dataclass(frozen=True, slots=True)
class ExternalRead:
    """Describe columns requested from a dataset managed outside Etlonomy."""

    dataset: ExternalDatasetId
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject empty or duplicate external read columns."""
        if not self.columns:
            raise ValueError('at least one column must be requested')
        if any(not column for column in self.columns):
            raise ValueError('requested column names must not be empty')
        if len(set(self.columns)) != len(self.columns):
            raise ValueError('requested columns must be unique')


DependencyRead = Read | ExternalRead


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Describe the environment and optional historical date for one execution.

    Each environment uses its own catalog. The environment name therefore labels the
    execution but does not select rows within a shared catalog. When ``as_of`` is
    omitted, catalog-backed providers resolve the currently valid dataset version.
    """

    environment: str | None = None
    as_of: date | None = None

    def __post_init__(self) -> None:
        """Reject an empty environment name."""
        if self.environment is not None and not self.environment.strip():
            raise ValueError('environment must not be empty')
        if self.environment is not None and self.environment != self.environment.strip():
            raise ValueError('environment must not have surrounding whitespace')


def read(dataset: DatasetId, *columns: str, version: int | None = None) -> Read:
    """Create a validated logical dataset read request."""
    return Read(dataset=dataset, columns=tuple(columns), version=version)


def external_read(dataset: ExternalDatasetId, *columns: str) -> ExternalRead:
    """Create a validated external dataset read request."""
    return ExternalRead(dataset=dataset, columns=tuple(columns))
