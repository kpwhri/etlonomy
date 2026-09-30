"""Environment-specific roots and SQL connections compiled into a catalog."""

import tomllib
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from etlonomy.exceptions import ManifestError
from etlonomy.manifest import Manifest

_ENVIRONMENT_FIELDS = frozenset(
    {'etlonomy_environment', 'environment', 'roots', 'connections'}
)
_ROOT_FIELDS = frozenset({'base_uri'})
_CONNECTION_FIELDS = frozenset({'sqlalchemy_url', 'credential_ref'})
_FILE_SOURCE_TYPES = frozenset({'csv', 'parquet', 'sas7bdat'})
_SQL_SOURCE_TYPES = frozenset({'sql_table', 'sql_query'})


@dataclass(frozen=True, slots=True)
class RootDefinition:
    """Define one shared base location for file-backed datasets."""

    name: str
    base_uri: str


@dataclass(frozen=True, slots=True)
class ConnectionDefinition:
    """Define one shared SQLAlchemy connection URL and credential reference."""

    name: str
    sqlalchemy_url: str
    credential_ref: str | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentDefinition:
    """Contain optional environment identity, roots, and SQL connections."""

    environment: str | None = None
    roots: tuple[RootDefinition, ...] = ()
    connections: tuple[ConnectionDefinition, ...] = ()


def _required_string(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f'{field_name} must be a non-empty string')
    return value


def _optional_string(value, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field_name)


def _reject_unknown_fields(value: dict, allowed: frozenset[str], context: str):
    for field_name in value.keys() - allowed:
        suggestion = get_close_matches(field_name, allowed, n=1)
        hint = f'; did you mean {suggestion[0]!r}?' if suggestion else ''
        raise ManifestError(f'unknown {context} field {field_name!r}{hint}')


def _named_tables(value, field_name: str) -> tuple[tuple[str, dict], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ManifestError(f'{field_name} must be a table')
    result = []
    for name, definition in value.items():
        _required_string(name, f'{field_name} name')
        if not isinstance(definition, dict):
            raise ManifestError(f'{field_name}.{name} must be a table')
        result.append((name, definition))
    return tuple(sorted(result))


def parse_environment(data: bytes) -> EnvironmentDefinition:
    """Parse and validate an environment TOML document."""
    try:
        raw = tomllib.loads(data.decode('utf8'))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ManifestError(f'invalid TOML environment configuration: {error}') from error
    if raw.get('etlonomy_environment') != 1:
        raise ManifestError('etlonomy_environment must equal 1')
    _reject_unknown_fields(raw, _ENVIRONMENT_FIELDS, 'environment')
    roots = []
    for name, definition in _named_tables(raw.get('roots'), 'roots'):
        _reject_unknown_fields(definition, _ROOT_FIELDS, f'root {name!r}')
        roots.append(
            RootDefinition(name, _required_string(definition.get('base_uri'), 'base_uri'))
        )
    connections = []
    for name, definition in _named_tables(raw.get('connections'), 'connections'):
        _reject_unknown_fields(
            definition, _CONNECTION_FIELDS, f'connection {name!r}'
        )
        sqlalchemy_url = _required_string(
            definition.get('sqlalchemy_url'), 'sqlalchemy_url'
        )
        try:
            make_url(sqlalchemy_url)
        except (ArgumentError, TypeError, ValueError) as error:
            raise ManifestError(
                'sqlalchemy_url must be a valid SQLAlchemy URL'
            ) from error
        connections.append(
            ConnectionDefinition(
                name,
                sqlalchemy_url,
                _optional_string(
                    definition.get('credential_ref'), 'credential_ref'
                ),
            )
        )
    return EnvironmentDefinition(
        environment=_optional_string(raw.get('environment'), 'environment'),
        roots=tuple(roots),
        connections=tuple(connections),
    )


def load_environment(path: Path) -> EnvironmentDefinition:
    """Load an environment TOML file with translated filesystem errors."""
    try:
        return parse_environment(path.read_bytes())
    except OSError as error:
        raise ManifestError(f'cannot read environment configuration {path}: {error}') from error


def validate_environment_references(manifest: Manifest, environment: EnvironmentDefinition):
    """Validate every shared root and connection referenced by a manifest."""
    roots = {item.name for item in environment.roots}
    connections = {item.name: item for item in environment.connections}
    for dataset in manifest.datasets:
        for version in dataset.versions:
            if version.source_type in _FILE_SOURCE_TYPES:
                if version.connection is not None:
                    raise ManifestError(
                        f'{version.source_type} source cannot declare connection'
                    )
                if version.source_root is not None and version.source_root not in roots:
                    raise ManifestError(f'unknown source_root: {version.source_root!r}')
                if version.source_root is not None and version.source_uri is not None:
                    relative_source = Path(version.source_uri)
                    if relative_source.is_absolute() or '..' in relative_source.parts:
                        raise ManifestError(
                            'source_uri must remain inside its configured source_root'
                        )
            elif version.source_type in _SQL_SOURCE_TYPES:
                if version.source_root is not None:
                    raise ManifestError(
                        f'{version.source_type} source cannot declare source_root'
                    )
                if (version.source_uri is None) == (version.connection is None):
                    raise ManifestError(
                        f'{version.source_type} requires exactly one of source_uri or connection'
                    )
                if version.connection is not None:
                    connection = connections.get(version.connection)
                    if connection is None:
                        raise ManifestError(
                            f'unknown connection: {version.connection!r}'
                        )
                    if (
                            version.credential_ref is not None
                            and connection.credential_ref is not None
                    ):
                        raise ManifestError(
                            f'{version.source_type} defines credential_ref both on the '
                            'dataset version and shared connection'
                        )
