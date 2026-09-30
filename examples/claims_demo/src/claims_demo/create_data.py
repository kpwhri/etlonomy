"""Create every local physical source used by the tutorial project."""

import sqlite3
from contextlib import closing
from pathlib import Path

import polars as pl


def create_sources(data_directory: Path = Path('data')):
    """Create claims, provider, and region sources without external services."""
    claims = pl.read_csv(data_directory / 'claim_line.csv')
    claims_parquet = data_directory / 'claim_line.parquet'
    claims_parquet.unlink(missing_ok=True)
    claims.write_parquet(claims_parquet)
    providers_parquet = data_directory / 'providers.parquet'
    providers_parquet.unlink(missing_ok=True)
    pl.DataFrame({
        'provider_id': [10, 20],
        'region_id': [100, 200],
    }).write_parquet(providers_parquet)
    claims_database = data_directory / 'claims.sqlite'
    claims_database.unlink(missing_ok=True)
    with closing(sqlite3.connect(claims_database)) as connection:
        with connection:
            connection.execute(
                'CREATE TABLE claim_line ('
                'person_id INTEGER, provider_id INTEGER, service_date TEXT, '
                'diagnosis_code TEXT)'
            )
            connection.executemany(
                'INSERT INTO claim_line VALUES (?, ?, ?, ?)',
                claims.iter_rows(),
            )
    reference_database = data_directory / 'reference.sqlite'
    reference_database.unlink(missing_ok=True)
    with closing(sqlite3.connect(reference_database)) as connection:
        with connection:
            connection.execute(
                'CREATE TABLE regions (region_id INTEGER, region_name TEXT)'
            )
            connection.executemany(
                'INSERT INTO regions VALUES (?, ?)', [(100, 'West'), (200, 'East')]
            )


if __name__ == '__main__':
    create_sources()
