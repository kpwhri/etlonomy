# Command-line reference

Use the command line to check TOML, build a catalog, preview a dated source, and generate Python dataset names.

Run `etlonomy --help` for the top level or
`etlonomy <group> <command> --help` for exact arguments.

## Build a catalog

Use these commands in order:

```console
# validate first so a typing mistake cannot replace the current good catalog
etlonomy catalog validate --manifest-dir manifests

# build one SQLite catalog from the valid TOML files
etlonomy catalog build --manifest-dir manifests --database .etlonomy/catalog.db

# check that the logical names you expected were actually included
etlonomy catalog show --database .etlonomy/catalog.db
```

Expected errors are printed in plain text and return a nonzero exit status. CI should treat that status as a failure.

Add `--environment-config environments/prod.toml` to `catalog validate` and `catalog build` when roots, connections, or
an optional environment name should be stored in the catalog.

## Preview source history and dates

```console
# history shows every dated source version for one logical dataset
etlonomy catalog history \
  --database .etlonomy/catalog.db \
  CLAIMS.CLAIM_LINE

# resolve shows the source a production or historical run will use
etlonomy catalog resolve \
  --database .etlonomy/catalog.db \
  CLAIMS.CLAIM_LINE \
  --as-of 2026-08-20
```

`--as-of` is optional and is mainly for historical reproduction. Omitting it resolves current data.

Use an explicit version only when reproducing or comparing a particular implementation. Normal runs should usually omit
both the date and version.

## Compare catalogs

```console
etlonomy catalog diff .etlonomy/catalog-old.db .etlonomy/catalog.db
```

The comparison reports added, removed, and changed datasets as JSON. “Changed” includes version dates, source metadata,
column mappings, credentials, options, and declared dependencies.

## Generate Python dataset names

```console
# generated names remove repeated strings and make misspellings fail during import
etlonomy codegen datasets \
  --database .etlonomy/catalog.db \
  --output src/claims_demo/datasets.py
```

The same catalog produces the same Python file. Run this after adding or removing logical dataset names. A source-only
change does not alter the generated names.

## Inspect jobs and lineage

```console
etlonomy registry validate --module claims_demo.jobs
etlonomy deps cohort.build --module claims_demo.jobs --database .etlonomy/catalog.db
etlonomy uses CLAIMS.CLAIM_LINE --module claims_demo.jobs --format json
etlonomy lineage CLAIMS.CLAIM_LINE --database .etlonomy/catalog.db --format json
etlonomy uses company_data:warehouse.claims --module claims_demo.jobs --format json
etlonomy lineage company_data:warehouse.claims --module claims_demo.jobs --format json
etlonomy graph cohort.build --module claims_demo.jobs --format dot
```

`--module` names the Python module that contains your decorated jobs and helpers. Importing it registers those
functions.
`--database` adds the dependencies from the dataset version selected by optional `--as-of`.
Names containing `:` are datasets loaded by a custom provider. They use the same `uses`
and `lineage` commands as catalog datasets. See the
[custom-provider guide](external-datasets.md) for the loading difference.

Choose the output that fits your next step:

- `text` is easiest for a person at a terminal
- `json` is easiest for another program
- `mermaid` embeds naturally in Markdown
- `dot` works with Graphviz

## Command summary

| Command                            | Primary question                               |
|------------------------------------|------------------------------------------------|
| `catalog validate`                 | Is my TOML valid?                              |
| `catalog build`                    | Can Etlonomy build the catalog?                |
| `catalog show`                     | Which logical datasets are present?            |
| `catalog history`                  | Which versions exist for this dataset?         |
| `catalog resolve`                  | Which source will this date or pin select?     |
| `catalog diff`                     | Which datasets or version metadata changed?    |
| `codegen datasets`                 | Can Python use generated stable names?         |
| `registry validate`                | Which ETL definitions registered successfully? |
| `deps`, `uses`, `lineage`, `graph` | How are jobs and datasets related?             |

Previous: [database connections](sqlalchemy.md) · Next:
[architecture](architecture.md)
