# Build your first catalog

This short guide creates one CSV source, describes it in TOML, and builds a catalog. The
[first project tutorial](tutorials/01-first-project.md) continues with generated dataset names, a working ETL job, and
tests.

## Create the folders

Keep source data, TOML, Python code, and tests in separate folders. This makes each file easier to find as the project
grows:

```text
claims-demo/
├── data/
├── manifests/
├── src/claims_demo/
└── tests/
```

Etlonomy provides the catalog and runtime tools. polars handles the rows and columns. Install both in the environment
where you will run the example:

```console
python -m pip install etlonomy polars
```

## Add a small CSV file

The catalog stores information about a source, not the source rows themselves. Create `data/claim_line.csv` so we have a
small file that is easy to check by eye:

```csv
person_id,service_date,diagnosis_code
1001,2026-08-01,I10
1002,2026-08-02,
1003,2026-08-03,E11
```

## Describe the CSV in TOML

A file path can change. Give the data the stable logical name `CLAIMS.CLAIM_LINE`, then record where this first version
lives and when it became valid. Create `manifests/claims.toml`:

```toml
etlonomy_manifest = 1

[[datasets]]
canonical_name = 'CLAIMS.CLAIM_LINE'
description = 'Claim lines used by cohort jobs.'

[[datasets.versions]]
version = 1
valid_from = 2026-01-01
source_type = 'csv'
source_uri = 'data/claim_line.csv'

[datasets.versions.options]
has_header = true
separator = ','
```

TOML dates are unquoted. See [TOML manifests](manifests.md) for every field.

## Check the TOML and build the catalog

TOML is easy to edit, which also makes it easy to mistype a field. Check it first. If the check passes, build the SQLite
catalog. Run these commands from `claims-demo/`:

```console
etlonomy catalog validate --manifest-dir manifests
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db
```

Validation prints `valid: 1 datasets`. The build prints a catalog hash. Building the same TOML again produces the same
hash.

## Check which source Etlonomy will use

A successful build means the TOML is valid. These commands let us check that the catalog contains one logical dataset,
one version, and the expected CSV for the example date:

```console
etlonomy catalog show --database .etlonomy/catalog.db
etlonomy catalog history --database .etlonomy/catalog.db CLAIMS.CLAIM_LINE
etlonomy catalog resolve --database .etlonomy/catalog.db \
  CLAIMS.CLAIM_LINE --as-of 2026-08-20
```

The commands list `CLAIMS.CLAIM_LINE`, show version `1`, and print the selected CSV information as JSON.

Next: [generate identifiers and run the first ETL](tutorials/01-first-project.md).
