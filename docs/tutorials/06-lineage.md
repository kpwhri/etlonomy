# Tutorial 6: see what the job uses

The completed job has two kinds of dependency:

- `cohort.build` directly reads claims and providers
- `attach_region` reads regions, and the ETL declares `uses=(attach_region,)`

Lineage should answer “what can this job read?” and “who uses this dataset?” without making someone follow every Python
call by hand.

## Step 1: build a graph from declarations

Import `claims_demo.jobs` before inspecting the registry. Decorators register metadata when Python imports their module.
Then add that registry to a graph:

```python
import etlonomy
from claims_demo import jobs  # noqa: F401

# add_registry reads declarations; it does not execute the ETL or open data sources
graph = etlonomy.LineageGraph()
graph.add_registry(etlonomy.registry)
```

The graph now knows the job's direct inputs, output, reusable helper, and the helper's required region dataset.

## Step 2: ask what the job may use

`declared_uses()` follows reusable helpers listed in `uses`. Its answer includes datasets that are not direct parameters
of the job:

```python
assert graph.declared_uses('cohort.build') == (
    Datasets.CLAIMS.CLAIM_LINE,
    Datasets.REFERENCE.PROVIDER,
    Datasets.REFERENCE.REGION,
)

assert graph.used_functions('cohort.build') == ('attach_region',)
```

The result always uses the same order, which helps tests and code review.

## Step 3: ask which code uses a dataset

You can also ask: “If I change regions, which jobs and helpers should I review?”

```python
assert graph.consumers(Datasets.REFERENCE.REGION) == ('cohort.build',)
assert graph.requirement_consumers(Datasets.REFERENCE.REGION) == (
    'attach_region',
)
```

The first answer includes the ETL because its declared `uses` reaches `attach_region`. The second answer names the
reusable function that owns the actual read declaration. These are related questions, not duplicate reports.

## Step 4: add the reads from an actual run

Declarations show what may run. The runtime record shows what one successful run actually read. Run the job, then add
that record to a new graph:

```python
result = runtime.run('cohort.build')
definition = etlonomy.registry.get_etl('cohort.build')

traced_graph = etlonomy.LineageGraph()
traced_graph.add_runtime_trace(
    definition.name,
    definition.outputs,
    runtime.last_dependencies,
)

assert traced_graph.uses('cohort.build') == (
    Datasets.CLAIMS.CLAIM_LINE,
    Datasets.REFERENCE.PROVIDER,
    Datasets.REFERENCE.REGION,
)
assert traced_graph.parents(jobs.COHORT_RESULT) == traced_graph.uses('cohort.build')
```

This describes one run, not every possible branch. Declarations and actual-run records are most useful together.

## Step 5: ask the same questions from the CLI

The CLI needs to import the module for the same registration reason. Run these from the project root:

```console
etlonomy deps cohort.build --module claims_demo.jobs --format json
etlonomy uses REFERENCE.REGION --module claims_demo.jobs --format json
etlonomy graph cohort.build --module claims_demo.jobs --format mermaid
```

The `uses` JSON separates `etl_jobs` from `reusable_functions`. The graph output contains typed job and function edges,
so a reader can see why the region dataset reaches the cohort output.

## Step 6: let Etlonomy reject loops

Etlonomy rejects loops in lineage graphs, helper `uses`, and TOML dependencies active during the same dates. Historical
dependencies may point in opposite directions when they are never active at the same time.

The main tutorial test checks `declared_uses` and runtime lineage after building all three sources in a temporary
directory.

---

[← Reusable functions](05-reusable-functions.md) · [Tutorial home](index.md) · [Next: migration →](07-migrating-a-source.md)
