# AST (Abstract Syntax Tree) Documentation

## Overview

The SAS Field Lineage Tracker uses an Abstract Syntax Tree (AST) to represent field dependencies and transformations in SAS code. This document explains the AST structure and how it's used to track field lineage.

## Core Data Structures

### FieldNode

The `FieldNode` is the fundamental building block of the AST. It represents a single field with all its metadata and dependencies.

```python
@dataclass
class FieldNode:
    name: str                           # Field name (e.g., "revenue")
    table: Optional[str]                # Table name (e.g., "sales_data")
    operation: Optional[FieldOperationType]  # Type of operation
    expression: Optional[str]           # SAS expression (e.g., "quantity * price")
    dependencies: List[FieldNode]       # List of fields this field depends on
    source_line: Optional[int]          # Line number in source code
    metadata: Dict[str, Any]            # Additional metadata
```

#### Field Operations

Fields can have different operation types:

- **ASSIGNMENT**: Simple assignment (e.g., `x = y;`)
- **CALCULATION**: Arithmetic calculation (e.g., `total = price * quantity;`)
- **FUNCTION**: SAS function call (e.g., `total = SUM(a, b, c);`)
- **MERGE**: Result of merging tables
- **FILTER**: Result of filtering data
- **RENAME**: Renamed field
- **DROP**: Field marked for dropping
- **KEEP**: Field marked for keeping

### DataStepNode

Represents a complete SAS DATA step:

```python
@dataclass
class DataStepNode:
    output_table: str                   # Output table name
    input_tables: List[str]             # Input table names (from SET/MERGE)
    fields: List[FieldNode]             # All fields in this step
    where_clause: Optional[str]         # WHERE condition
    merge_keys: List[str]               # BY variables for merging
```

### SASProgram

Container for the entire SAS program:

```python
class SASProgram:
    data_steps: List[DataStepNode]      # All DATA steps
    proc_steps: List[ProcStepNode]      # All PROC steps
    all_fields: Dict[str, List[FieldNode]]  # Index: field_name -> [FieldNode]
```

## Example: Building an AST

### SAS Code

```sas
DATA raw_sales;
    SET input_data;
    revenue = quantity * price;
    discount_amount = revenue * discount_rate;
RUN;

DATA final_sales;
    SET raw_sales;
    net_revenue = revenue - discount_amount;
    profit = net_revenue - cost;
RUN;
```

### Resulting AST Structure

```
SASProgram
├── DataStepNode: raw_sales
│   ├── input_tables: [input_data]
│   └── fields:
│       ├── FieldNode: revenue
│       │   ├── expression: "quantity * price"
│       │   ├── operation: ASSIGNMENT
│       │   └── dependencies:
│       │       ├── FieldNode: quantity (from input_data)
│       │       └── FieldNode: price (from input_data)
│       └── FieldNode: discount_amount
│           ├── expression: "revenue * discount_rate"
│           ├── operation: ASSIGNMENT
│           └── dependencies:
│               ├── FieldNode: revenue (from raw_sales)
│               └── FieldNode: discount_rate (from input_data)
└── DataStepNode: final_sales
    ├── input_tables: [raw_sales]
    └── fields:
        ├── FieldNode: net_revenue
        │   ├── expression: "revenue - discount_amount"
        │   ├── operation: ASSIGNMENT
        │   └── dependencies:
        │       ├── FieldNode: revenue (from raw_sales)
        │       └── FieldNode: discount_amount (from raw_sales)
        └── FieldNode: profit
            ├── expression: "net_revenue - cost"
            ├── operation: ASSIGNMENT
            └── dependencies:
                ├── FieldNode: net_revenue (from final_sales)
                └── FieldNode: cost (from raw_sales)
```

## Lineage Graph

The AST is transformed into a directed graph where:
- **Nodes** represent fields (with unique ID: `table.field`)
- **Edges** represent dependencies (A → B means B depends on A)

### Example Graph

```
input_data.quantity ──┐
                      ├──> raw_sales.revenue ──┐
input_data.price ─────┘                       │
                                              ├──> final_sales.net_revenue ──┐
input_data.discount_rate ──┐                  │                              │
                           ├──> raw_sales.discount_amount ──────────────────┘
input_data.revenue ────────┘                                                 │
                                                                             ├──> final_sales.profit
raw_sales.cost ──────────────────────────────────────────────────────────────┘
```

## Using the AST

### 1. Query for a Field

```python
from sas_lineage.parser import SASParser
from sas_lineage.lineage import LineageTracker

# Parse SAS code
parser = SASParser()
program = parser.parse(sas_code)

# Create tracker
tracker = LineageTracker(program)

# Query for a field
result = tracker.query_field('profit', 'final_sales')

# Access field information
field_info = result['results'][0]['field']
print(f"Expression: {field_info['expression']}")
print(f"Dependencies: {field_info['dependencies']}")
```

### 2. Browse All Fields

```python
# Browse all fields
browse_result = tracker.browse_fields()

print(f"Total fields: {browse_result['stats']['total_fields']}")
print(f"Tables: {browse_result['all_tables']}")

# Fields by table
for table, fields in browse_result['fields_by_table'].items():
    print(f"\n{table}:")
    for field in fields:
        print(f"  - {field['name']}: {field['expression']}")
```

### 3. Trace Lineage Path

```python
# Find path between two fields
path = tracker.get_lineage_path('quantity', 'profit')
print(" → ".join(path))
# Output: input_data.quantity → raw_sales.revenue → final_sales.net_revenue → final_sales.profit
```

### 4. Export Visualization

```python
# Export to DOT format for GraphViz
dot_graph = tracker.export_graph_dot()
with open('lineage.dot', 'w') as f:
    f.write(dot_graph)

# Visualize at: https://dreampuf.github.io/GraphvizOnline/
```

## Advanced Features

### Recursive Dependency Resolution

The AST supports recursive traversal of dependencies:

```python
field = program.find_field('profit')[0]

# Get all upstream dependencies
all_deps = field.get_all_dependencies()
for dep in all_deps:
    print(f"  {dep.table}.{dep.name}")
```

### Lineage Depth Calculation

Calculate how many transformation steps a field has:

```python
depth = tracker._calculate_lineage_depth(field)
print(f"Lineage depth: {depth}")
# Higher depth = more transformations from source
```

### Field Metadata

Store additional information in field metadata:

```python
field.metadata = {
    'data_type': 'numeric',
    'format': 'dollar12.2',
    'label': 'Total Profit Amount',
    'business_definition': 'Net revenue minus costs'
}
```

## Best Practices

1. **Unique Field Identification**: Always use `table.field` format for unique identification
2. **Dependency Tracking**: Keep dependency lists clean and avoid circular dependencies
3. **Metadata Usage**: Use metadata for business context, not for lineage logic
4. **Graph Traversal**: Use NetworkX graph methods for complex queries
5. **Performance**: Index fields by name for fast lookup in large programs

## Limitations

The current AST implementation has some limitations:

- **No Macro Expansion**: SAS macros are not expanded
- **Limited PROC Support**: Only basic PROC steps are parsed
- **Simple Expression Parsing**: Complex expressions may not be fully parsed
- **No Data Flow Analysis**: Only structural dependencies are tracked

For production use with complex SAS programs, consider:
- Integrating with SAS Metadata Server
- Using SAS APIs for more accurate parsing
- Implementing proper SAS macro processor
- Adding data type inference and validation

## References

- [Abstract Syntax Trees](https://en.wikipedia.org/wiki/Abstract_syntax_tree)
- [Directed Acyclic Graphs](https://en.wikipedia.org/wiki/Directed_acyclic_graph)
- [Data Lineage](https://en.wikipedia.org/wiki/Data_lineage)
- [SAS Language Reference](https://support.sas.com/)
