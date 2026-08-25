# See what data each job uses

Lineage answers practical questions:

- Which datasets feed this output?
- Which outputs would be affected if this source changed?
- Which ETL jobs use a sensitive dataset?
- Did a reusable helper introduce another read at runtime?

Etlonomy uses the dependencies you list. It does not guess from SQL text.

## Read a lineage arrow

An edge points from upstream data to downstream data:

```text
CLAIMS.CLAIM_LINE ──> CLAIMS.ENRICHED_CLAIMS
```

Build a graph directly:

```python
graph = etlonomy.LineageGraph()
claims = Datasets.CLAIMS.CLAIM_LINE
providers = Datasets.REFERENCE.PROVIDER
enriched = Datasets.CLAIMS.ENRICHED_CLAIMS

# these edges state that enriched claims cannot be produced without both inputs
graph.add_dependency(enriched, [claims, providers])
```

Now ask different questions:

```python
# parents are immediate inputs to enriched
print(graph.parents(enriched))

# children are immediate outputs depending on claims
print(graph.children(claims))

# ancestors and descendants continue through every reachable level
print(graph.ancestors(enriched))
print(graph.descendants(claims))
```

The same graph always returns results in the same order. Etlonomy raises `DependencyCycleError` when a new arrow would
create a loop, because a loop has no clear beginning or end.

## Compare declared use with an actual run

The registry knows direct `@etl` inputs and reusable functions declared through `uses`:

```python
graph.add_registry(etlonomy.registry)
print(graph.consumers(Datasets.CLAIMS.CLAIM_LINE))
print(graph.declared_uses('cohort.build'))
print(graph.used_functions('cohort.build'))
```

The declared graph shows what the job may call. A helper may run only under certain conditions, so one run can differ.
Run the job and add the reads that Etlonomy recorded:

```python
# running the job records direct reads and any requirements actually injected
runtime.run('cohort.build')
definition = etlonomy.registry.get_etl('cohort.build')

graph.add_runtime_trace(
    definition.name,
    definition.outputs,
    runtime.last_dependencies,
)

# uses now includes direct ETL inputs and requirements reached during this run
print(graph.uses('cohort.build'))
```

Declarations show what may be used. The runtime record shows what one run actually used. Looking at both gives the
clearest answer.

Datasets loaded by a custom provider appear in these same results. The provider changes
how a dataset is loaded, not how lineage treats it:

```python
print(graph.declared_uses('cohort.build'))
print(graph.uses('cohort.build'))
print(graph.consumers(CUSTOM_CLAIMS))
print(graph.descendants(CUSTOM_CLAIMS))
```

The `external_*` methods remain as compatibility helpers when older code wants only
`ExternalDatasetId` values. See [custom-loaded datasets](external-datasets.md) for the
provider rules and a complete testing example.

## Choose a graph format

```console
# Mermaid is convenient inside Markdown documentation
etlonomy graph cohort.build --format mermaid

# DOT works well with Graphviz tooling
etlonomy graph cohort.build --format dot

# JSON is easiest for another program to consume
etlonomy uses CLAIMS.CLAIM_LINE --module claims_demo.jobs --format json
```

Pass `--module` when a command needs your application's registered jobs. The command imports that module instead of
searching every Python file.

Previous: [external datasets](external-datasets.md) · Next:
[choose file source types](files.md)
