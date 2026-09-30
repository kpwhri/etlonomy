"""Run the example ETL for a requested historical date."""

import argparse
from datetime import date
from pathlib import Path

import etlonomy
from claims_demo import jobs  # noqa: F401


def main():
    """Resolve and execute the example ETL."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', type=date.fromisoformat)
    arguments = parser.parse_args()
    provider = etlonomy.CatalogDatasetProvider(
        catalog=etlonomy.SQLiteCatalog(Path('.etlonomy/catalog.db')),
    )
    runtime = etlonomy.Runtime(
        provider=provider,
        context=etlonomy.ExecutionContext(as_of=arguments.as_of),
    )
    result = runtime.run('cohort.build').collect()
    print(result.to_dict(as_series=False))


if __name__ == '__main__':
    main()
