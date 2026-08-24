# ETLonomy claims demo

This is the finished snapshot of the project built throughout `docs/tutorials/`. It creates claims in csv, parquet, and
sqlite, provider data in parquet, and region data in sqlite. Its ETL reads claims and providers directly while an
`@etlonomy.requires` helper reads regions.

From this directory:

```text
PYTHONPATH=src python -m claims_demo.create_data
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db
etlonomy codegen datasets --database .etlonomy/catalog.db --output src/claims_demo/datasets.py
PYTHONPATH=src python -m claims_demo.run --as-of 2026-08-20
PYTHONPATH=src python -m claims_demo.run --as-of 2026-09-01
PYTHONPATH=src python -m claims_demo.run --as-of 2027-01-01
```

The three runs resolve CSV, Parquet, and sqlite claims respectively while executing the same `cohort.build` ETL.
Provider and region sources remain independent, so each run also exercises reusable dependency injection. The canonical
end-to-end fixture in `tests/end_to_end/test_documentation_example.py` rebuilds every tutorial phase in a temporary
directory, runs production-like and isolated test data, and verifies lineage and dataset uses.
