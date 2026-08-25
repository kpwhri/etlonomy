# Etlonomy

Etlonomy helps ETL jobs read data without tying the Python code to one file, table, or server. A job asks for a logical
name such as `CLAIMS.CLAIM_LINE`. TOML files tell Etlonomy whether that name currently points to CSV, Parquet, SAS7BDAT,
or a SQL database.

## What you can do with Etlonomy

- Describe logical datasets and their dated sources in TOML
- Build a small SQLite catalog that Etlonomy can read quickly
- Return polars `LazyFrame` objects and request only the columns a job needs
- Declare data used by `@etl` jobs and `@requires` helper functions
- Track named external datasets without building their source library into Etlonomy
- Test with supplied data that can never fall back to production
- Inspect catalogs, generate dataset names, and ask lineage questions from the command line

## Where to start

- **Build the example project:** follow the [tutorials in order](tutorials/index.md)
- **Set up your own project:** use the [implementation checklist](implementation-checklist.md)
- **Understand the main ideas:**
  read [how Etlonomy thinks about data](concepts.md), [logical dataset names](datasets.md),
  and [source dates](versioning.md)
- **Connect data:** see [files](files.md), [SQL](sql.md), or [sqlalchemy connections](sqlalchemy.md)
- **Test without production:** see [testing](testing.md)
- **Use another data library:** see [external datasets](external-datasets.md)
- **Move a dataset:** follow [migrating a source](tutorials/07-migrating-a-source.md)

```text
manifests/*.toml
        |
        v
.etlonomy/catalog.db ---> generated datasets.py
        |                         |
        +------------+------------+
                     v
                Runtime.run()
                     |
                     v
              polars LazyFrame
```

Next: [install Etlonomy and build a small catalog](getting-started.md).

## Follow the tutorial course

1. [Build and run the first project](tutorials/01-first-project.md)
2. [Migrate CSV to Parquet](tutorials/02-csv-and-parquet.md)
3. [Add Parquet and SQLite reference sources](tutorials/03-sql-dataset.md)
4. [Test production-like and isolated execution](tutorials/04-testing.md)
5. [Add reusable data requirements](tutorials/05-reusable-functions.md)
6. [Inspect lineage and uses](tutorials/06-lineage.md)
7. [Run the complete source migration](tutorials/07-migrating-a-source.md)
8. [Add shared connections and optional credentials](tutorials/08-credentials.md)

After the numbered path, try the [SAS7BDAT](tutorials/09-sas7bdat.md) or
[remote SQL database](tutorials/10-sql-databases.md) extension. If another Python library
already loads your data, follow the [custom provider](tutorials/11-custom-provider.md)
extension.

For prerequisites, learning paths, and optional branches, open the
[tutorial home](tutorials/index.md).
