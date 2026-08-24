# Optional extension A: read an older SAS7BDAT source

Install the optional SAS reader only where a job will read SAS7BDAT files:

```console
python -m pip install 'etlonomy[sas]'
```

Suppose an older file uses `member_id`, `svc_dt`, and `diagnosis_cd`. Map them to the clearer names used by the ETL job:

```toml
[[datasets.versions]]
version = 1
valid_from = 2025-01-01
valid_to = 2026-01-01
source_type = 'sas7bdat'
source_uri = 'data/claim_line.sas7bdat'

[datasets.versions.columns.person_id]
source = 'member_id'

[datasets.versions.columns.service_date]
source = 'svc_dt'

[datasets.versions.columns.diagnosis_code]
source = 'diagnosis_cd'
```

`jobs.py` still requests `person_id` and `diagnosis_code`. Etlonomy requests the mapped source columns when supported,
renames them, and returns a lazy polars frame. The SAS reader itself may be eager.

The repository includes two small, committed fixtures under `tests/fixtures/`: `claim_line.sas7bdat` and
`provider.sas7bdat`. Integration tests read them through the normal `SasAdapter` and `CatalogDatasetProvider`; missing
files fail the suite rather than silently skipping. The end-to-end acceptance test joins claims to provider specialties,
runs the same ETL before and after a temporary SQLite migration, and verifies dependencies and lineage.

A unit test may supply a fake reader when it is testing reader errors. Integration and migration tests should use the
committed SAS files and must never depend on a production shared drive.

See [file-source behavior](../files.md) and the
[migration tutorial](07-migrating-a-source.md).
---

[← Source migration](07-migrating-a-source.md) · [Tutorial home](index.md) · [Next extension: remote SQL →](10-sql-databases.md)
