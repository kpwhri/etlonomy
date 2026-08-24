"""Apply ordered SQL migrations to ETLonomy SQLite catalogs."""

import re
import sqlite3
from pathlib import Path

from etlonomy.exceptions import CatalogError

_MIGRATION_NAME = re.compile(r'^(\d+)_.*\.sql$')
DEFAULT_MIGRATION_DIRECTORY = Path(__file__).with_name('migrations')
CURRENT_SCHEMA_VERSION = 3
_STATEMENT_SEPARATOR = '-- etlonomy:next-statement'


def discover_migrations(
        path: Path = DEFAULT_MIGRATION_DIRECTORY,
) -> tuple[tuple[int, Path], ...]:
    """Return migrations in numeric order while rejecting duplicate numbers."""
    migrations: list[tuple[int, Path]] = []
    seen: set[int] = set()
    for file in sorted(path.glob('*.sql')):
        match = _MIGRATION_NAME.fullmatch(file.name)
        if match is None:
            continue
        number = int(match.group(1))
        if number in seen:
            raise CatalogError(f'duplicate migration number: {number}')
        seen.add(number)
        migrations.append((number, file))
    return tuple(sorted(migrations))


def apply_migrations(
        connection: sqlite3.Connection, path: Path = DEFAULT_MIGRATION_DIRECTORY
) -> None:
    """Apply pending migrations atomically and enable foreign-key enforcement."""
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        connection.execute('BEGIN')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS schema_version '
            '(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL '
            'DEFAULT CURRENT_TIMESTAMP)'
        )
        applied = {
            row[0] for row in connection.execute('SELECT version FROM schema_version')
        }
        pending = [
            (number, file)
            for number, file in discover_migrations(path)
            if number not in applied
        ]
        for number, file in pending:
            for statement in _read_statements(file):
                connection.execute(statement)
            connection.execute(
                'INSERT INTO schema_version (version) VALUES (?)', (number,)
            )
        connection.commit()
    except CatalogError:
        connection.rollback()
        raise
    except (OSError, sqlite3.Error) as error:
        connection.rollback()
        raise CatalogError(f'catalog migration failed: {error}') from error


def _read_statements(path: Path) -> tuple[str, ...]:
    content = path.read_text(encoding='utf8')
    statements = tuple(
        statement.strip()
        for statement in content.split(_STATEMENT_SEPARATOR)
        if statement.strip()
    )
    if not statements:
        raise CatalogError(f'catalog migration contains no SQL: {path.name}')
    return statements
