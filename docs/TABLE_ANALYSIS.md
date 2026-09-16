# Table resolution: first compatibility milestone

The table report exposes what the analyzer knows and where further execution
evidence is needed. It does not claim to be a complete SAS compiler, runtime,
or program scheduler. No SAS executable was available for reference runs during
this milestone; the regression fixtures check the declared subset and locally
reproduced defects, not full conformance against SAS.

## Run it

```bash
PYTHONPATH=src python -m sas_lineage.cli examples/table_resolution.sas --tables
PYTHONPATH=src python -m sas_lineage.cli examples/table_resolution.sas --tables --strict -o tables.json
PYTHONPATH=src python -m sas_lineage.cli examples/sales_analysis.sas --tables --expand-macros
```

`--tables` prints only JSON to stdout and needs no third-party Python packages.
`--strict` exits with status 2 if the report is partial, after emitting and saving
the report. Without strict mode, partial analysis is a successful report (exit 0).
Read/write errors return 1. `--default-library work` explicitly identifies
one-level names with the logical WORK library. Without it, one-level names use
an unspecified default library and are not equated with WORK-qualified names.

Existing field queries, browsing and UI entry points remain available. Qualified
names are now preserved, so callers relying on the old erroneous truncation
must use the full names. The legacy field extractor still assigns fields to
the primary DATA output; multiple output table references are covered by this
report, not by full multi-output field semantics.

## API

```python
from sas_lineage.parser import SASParser
from sas_lineage.analysis import build_table_report

program = SASParser().parse(source)
report = build_table_report(program, source_name="job.sas", default_library="work")
```

`program.steps` preserves DATA/PROC interleaving. The existing `data_steps` and
`proc_steps` lists remain available for compatibility. Each step has a source
line and typed table references. `DATA _NULL_` remains a step but produces no
dataset. `get_tables()` includes symbolic expressions; use the report when you
need to distinguish literal names from unresolved names.

## Evidence and coverage

- **literal** means the dataset name contains no unresolved macro expression.
  It does not mean the step has run or succeeded.
- **symbolic** preserves the original macro expression, such as
  `mart.sales_&period.`. It never produces a concrete dataset graph node.
- **unknown** retains unsupported or session-dependent names such as `_LAST_`
  without fabricating a concrete dataset identity.
- **static_subset** means this pass found no diagnostic within its declared
  subset. It is not a claim of universal SAS support or runtime validation.
- **partial** means unresolved or unsupported behavior was detected. Read the
  diagnostics before consuming candidate graph edges.

Every report includes `coordinate_space`. With no preprocessing, line numbers
refer to the source. With `--expand-macros`, they refer to expanded text. Original
macro/include source maps are a future milestone; expanded lines must not be
presented as original-file locations.

The existing macro preprocessor remains a heuristic compatibility path. Every
report using it is partial and marks evidence as `heuristic_expansion`, even
when the expanded names look literal. Unresolved variables and unknown macro
invocations are preserved, single-quoted text is protected, and an empty `%LET`
clears the prior value. These fixes do not establish complete scoping, quoting,
rescanning or execution-timing semantics. In particular, an unknown condition
can still select an incorrect branch in the legacy preprocessor.

## Supported table-extraction subset

- Quote-aware statement boundaries, doubled quote escapes, block/statement
  comments, and opaque DATALINES/CARDS and DATALINES4/CARDS4 bodies.
- Explicit DATA output lists, SET/MERGE inputs, two-level names, SAS name
  literals, and skipping parenthesized dataset options.
- Step order, including a following DATA/PROC statement terminating a prior step.
- Common procedure DATA=/OUT= options in both headers and body statements;
  SORT in-place writes, duplicate outputs, and APPEND BASE read/write effects.
- Basic SQL CREATE TABLE/FROM/JOIN recovery, always marked partial because SQL
  grammar, aliases, CTEs, pass-through SQL and mutations are not fully modeled.
- Diagnostics for runtime macro effects, unexpanded macros, prefix/range lists,
  session configuration, external/hash I/O, conditional dataset I/O, ODS,
  deferred DATA views, unsupported procedures and malformed scanner input.

The graph versions literal logical datasets in source order. Each step reads
the versions visible at its entry, then creates a new version for each write.
Thus reading and rewriting the same table does not generate a self-dependency.
Quoted member names are decoded without confusing embedded dots with library
separators. The graph is candidate evidence whenever the report is partial.

`graph.safe_to_schedule` is always false. The report does not infer physical
library alias equivalence, cross-file session boundaries, conditional writes,
write/write ordering, or hidden external effects. `source_order` is the observed
parse order, not a computed program-level topological sort.

## Next implementation boundaries

1. Replace heuristic macro expansion with a stateful interpreter and source
   maps: frames, symbol scope, masked text, rescanning, and explicit unknown
   values/conditions. Build the function registry against SAS reference cases.
2. Model execution hooks for SYMPUTX, SQL INTO, CALL EXECUTE and DOSUBL, using
   supplied control-data/catalog snapshots or imported runtime traces.
3. Resolve libraries, catalog-dependent names, procedure contracts and SQL.
4. Combine program invocations under an explicit run manifest. Add producer
   conflicts, control/state constraints and cycle explanations before emitting
   a scheduling order.
5. Compare names, I/O effects and timing against SAS on a representative held-out
   corpus. Capture version, parameters, startup files and session boundaries.

## Theory worth studying alongside the implementation

- [Crafting Interpreters, part II](https://craftinginterpreters.com/contents.html):
  scanning, syntax trees, evaluation, state, control flow, functions, resolving
  and binding. These map directly to the scanner and macro interpreter.
- [Stanford CS143](https://web.stanford.edu/class/cs143/): lexical analysis,
  parsing, semantic analysis, runtime environments and operational semantics.
- [Patrick Cousot's abstract interpretation material](https://www.di.ens.fr/~cousot/AI/):
  abstract values, soundness, joins and fixed points. These underpin exact vs
  possible vs unknown table names. Add reaching definitions and SSA concepts
  when extending dataset versioning and inter-program dependencies.

Code generation, register allocation and optimization are lower priority for
this analyzer. SAS documentation and differential execution fixtures remain
the authority for SAS-specific behavior.

## Verification

```bash
uv run --with pytest --with pandas --with networkx --with openpyxl pytest -q
```

The full suite includes scanner edge cases, the five original failure probes,
macro preservation, dataset versioning and strict CLI JSON output. The existing
field evaluator emits deprecation warnings unrelated to this milestone.
