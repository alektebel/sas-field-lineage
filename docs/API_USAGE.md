# API Usage Guide

This guide demonstrates how to use the SAS Field Lineage Tracker programmatically in your Python applications.

## Installation

```bash
pip install -e .
```

Or install from requirements:

```bash
pip install -r requirements.txt
```

## Basic Usage

### Parsing SAS Code

```python
from sas_lineage.parser import SASParser

# Create parser instance
parser = SASParser()

# Parse SAS code from string
sas_code = """
DATA output;
    SET input;
    total = quantity * price;
RUN;
"""

program = parser.parse(sas_code)

# Access parsed information
print(f"Found {len(program.data_steps)} data steps")
print(f"Output tables: {[ds.output_table for ds in program.data_steps]}")
```

### Parsing from File

```python
from pathlib import Path

# Read SAS file
sas_file = Path('examples/sales_analysis.sas')
with open(sas_file, 'r') as f:
    sas_code = f.read()

# Parse
program = parser.parse(sas_code)
```

## Working with the AST

### Accessing Fields

```python
# Get all fields
all_fields = program.get_all_fields()
print(f"Total fields: {len(all_fields)}")

# Find specific field
revenue_fields = program.find_field('revenue')
for field in revenue_fields:
    print(f"Found: {field.table}.{field.name}")
    print(f"Expression: {field.expression}")
    print(f"Dependencies: {[d.name for d in field.dependencies]}")
```

### Working with Data Steps

```python
# Iterate through data steps
for data_step in program.data_steps:
    print(f"\nData Step: {data_step.output_table}")
    print(f"  Input tables: {data_step.input_tables}")
    print(f"  Merge keys: {data_step.merge_keys}")
    
    # Access fields in this step
    for field in data_step.fields:
        print(f"  - {field.name}: {field.expression}")
```

## Lineage Tracking

### Creating a Tracker

```python
from sas_lineage.lineage import LineageTracker

# Create tracker from parsed program
tracker = LineageTracker(program)
```

### Querying Fields

```python
# Query by field name only
result = tracker.query_field('profit')

if result['found']:
    print(f"Found {result['count']} instance(s)")
    
    for res in result['results']:
        field = res['field']
        print(f"\nField: {res['node_id']}")
        print(f"Expression: {field['expression']}")
        print(f"Upstream: {res['upstream']}")
        print(f"Downstream: {res['downstream']}")
        print(f"Depth: {res['depth']}")

# Query with table name
result = tracker.query_field('profit', table_name='final_sales')
```

### Browse All Fields

```python
# Browse all fields
browse_result = tracker.browse_fields()

# Get statistics
stats = browse_result['stats']
print(f"Total fields: {stats['total_fields']}")
print(f"Total tables: {stats['total_tables']}")
print(f"Fields with dependencies: {stats['fields_with_dependencies']}")
print(f"Max lineage depth: {stats['max_depth']}")

# Browse fields by table
for table_name, fields in browse_result['fields_by_table'].items():
    print(f"\n{table_name}: {len(fields)} fields")

# Filter by table
sales_fields = tracker.browse_fields(table_name='sales_data')
```

### Finding Lineage Paths

```python
# Find path between two fields
path = tracker.get_lineage_path(
    from_field='quantity',
    to_field='profit',
    from_table='input_data',
    to_table='final_sales'
)

if path:
    print("Lineage path:")
    print(" → ".join(path))
else:
    print("No path found")
```

### Graph Operations

```python
import networkx as nx

# Access the underlying graph
graph = tracker.graph

# Graph statistics
print(f"Nodes: {graph.number_of_nodes()}")
print(f"Edges: {graph.number_of_edges()}")

# Find all ancestors of a field
field_id = "final_sales.profit"
ancestors = nx.ancestors(graph, field_id)
print(f"All upstream fields: {ancestors}")

# Find all descendants
descendants = nx.descendants(graph, field_id)
print(f"All downstream fields: {descendants}")
```

## Field Evaluation

### Manual Value Entry

```python
from sas_lineage.lineage import FieldEvaluator

# Create evaluator
evaluator = FieldEvaluator(program)

# Get a field to evaluate
field = program.find_field('revenue')[0]

# Provide input values
input_data = {
    'quantity': 10,
    'price': 100
}

# Evaluate
result = evaluator.evaluate_field(field, input_data)
print(f"Result: {result}")  # Output: 1000
```

### CSV/Excel Input

```python
import pandas as pd

# Load from CSV
df = evaluator.load_data_from_csv('examples/sample_data.csv', 'input_data')
print(df.head())

# Load from Excel
df = evaluator.load_data_from_excel('data.xlsx', sheet_name='Sheet1')

# Evaluate with DataFrame
result_df = evaluator.evaluate_with_dataframe(
    table_name='output',
    df=df,
    output_fields=['revenue', 'profit']  # Optional: specific fields
)

print(result_df)

# Save results
result_df.to_csv('results.csv', index=False)
result_df.to_excel('results.xlsx', index=False)
```

## Visualization

### Export to DOT Format

```python
# Export lineage graph
dot_graph = tracker.export_graph_dot()

# Save to file
with open('lineage.dot', 'w') as f:
    f.write(dot_graph)

print("Graph saved to lineage.dot")
print("Visualize at: https://dreampuf.github.io/GraphvizOnline/")
```

### Using GraphViz (if installed)

```python
try:
    import graphviz
    
    # Create graph
    g = graphviz.Source(dot_graph)
    
    # Render to file
    g.render('lineage', format='png', cleanup=True)
    print("Graph rendered to lineage.png")
    
except ImportError:
    print("GraphViz not installed. Install with: pip install graphviz")
```

## Advanced Usage

### Custom Field Analysis

```python
from sas_lineage.ast import FieldNode, FieldOperationType

# Analyze field operations
for field in program.get_all_fields():
    if field.operation == FieldOperationType.ASSIGNMENT:
        if field.expression and '*' in field.expression:
            print(f"Multiplication field: {field.table}.{field.name}")
```

### Dependency Analysis

```python
# Find fields with most dependencies
fields_by_dep_count = sorted(
    program.get_all_fields(),
    key=lambda f: len(f.dependencies),
    reverse=True
)

print("Fields with most dependencies:")
for field in fields_by_dep_count[:5]:
    print(f"  {field.name}: {len(field.dependencies)} dependencies")
```

### Lineage Depth Analysis

```python
# Analyze lineage depths
depth_map = {}
for field in program.get_all_fields():
    depth = tracker._calculate_lineage_depth(field)
    if depth not in depth_map:
        depth_map[depth] = []
    depth_map[depth].append(f"{field.table}.{field.name}")

print("Fields by lineage depth:")
for depth in sorted(depth_map.keys()):
    print(f"  Depth {depth}: {len(depth_map[depth])} fields")
```

### JSON Export

```python
import json

# Export field information to JSON
fields_json = []
for field in program.get_all_fields():
    fields_json.append(field.to_dict())

with open('fields.json', 'w') as f:
    json.dump(fields_json, f, indent=2)

# Export lineage results
result = tracker.query_field('profit')
with open('lineage_result.json', 'w') as f:
    json.dump(result, f, indent=2)
```

## Integration Examples

### Flask API

```python
from flask import Flask, request, jsonify
from sas_lineage.parser import SASParser
from sas_lineage.lineage import LineageTracker

app = Flask(__name__)

@app.route('/parse', methods=['POST'])
def parse_sas():
    sas_code = request.json['code']
    
    parser = SASParser()
    program = parser.parse(sas_code)
    tracker = LineageTracker(program)
    
    return jsonify(tracker.browse_fields())

@app.route('/query/<field_name>', methods=['GET'])
def query_field(field_name):
    # Assume program is stored somewhere (session, cache, etc.)
    result = tracker.query_field(field_name)
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)
```

### Batch Processing

```python
from pathlib import Path

def process_sas_files(directory):
    """Process all SAS files in a directory"""
    results = {}
    
    for sas_file in Path(directory).glob('**/*.sas'):
        print(f"Processing {sas_file}...")
        
        with open(sas_file, 'r') as f:
            sas_code = f.read()
        
        parser = SASParser()
        program = parser.parse(sas_code)
        tracker = LineageTracker(program)
        
        results[str(sas_file)] = {
            'fields': len(program.get_all_fields()),
            'tables': len(program.get_tables()),
            'data_steps': len(program.data_steps)
        }
    
    return results

# Use it
results = process_sas_files('sas_programs/')
print(json.dumps(results, indent=2))
```

## Error Handling

```python
try:
    parser = SASParser()
    program = parser.parse(sas_code)
    tracker = LineageTracker(program)
    
    result = tracker.query_field('myfield')
    
    if not result['found']:
        print(f"Field 'myfield' not found in the program")
    
except Exception as e:
    print(f"Error processing SAS code: {str(e)}")
```

## Best Practices

1. **Reuse Parser Instances**: Create parser once for multiple files
2. **Cache Results**: Store parsed programs for repeated queries
3. **Validate Input**: Check that SAS code is well-formed
4. **Handle Large Files**: Use streaming for very large SAS files
5. **Error Logging**: Log parsing errors for debugging

## Performance Tips

- Use `browse_fields(table_name=...)` to filter early
- Cache tracker instances for interactive use
- Use NetworkX graph methods for complex queries
- Index frequently queried fields

## See Also

- [AST Documentation](AST_DOCUMENTATION.md)
- [Quick Start Guide](../QUICKSTART.md)
- [README](../README.md)
