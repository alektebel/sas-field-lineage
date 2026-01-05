# Features Overview

## Core Features

### 1. AST-Based Field Representation 🌳

The tracker uses an Abstract Syntax Tree (AST) to represent fields and their dependencies:

- **FieldNode**: Represents each field with metadata, expression, and dependencies
- **DataStepNode**: Represents SAS DATA steps with input/output tables
- **SASProgram**: Container for the entire parsed program
- **Recursive Dependency Resolution**: Trace dependencies through multiple levels

**Example:**
```python
field = FieldNode(
    name="profit",
    table="sales",
    expression="revenue - cost",
    dependencies=[revenue_field, cost_field]
)
```

### 2. Query Functionality 🔍

Search for specific fields and explore their lineage:

- **Field Search**: Find fields by name or table
- **Upstream Dependencies**: See what fields contribute to a field's value
- **Downstream Dependencies**: See what fields depend on a field
- **Lineage Depth**: Calculate transformation distance from source data
- **Lineage Paths**: Find paths between any two fields

**Example:**
```python
result = tracker.query_field('profit', table_name='final_sales')
# Returns complete lineage information
```

### 3. Browse Functionality 📊

Explore all fields in your SAS program:

- **Table-Based Grouping**: View fields organized by table
- **Statistics**: Total fields, tables, dependencies, max depth
- **Filtering**: Filter by table name
- **Field Details**: Expression, operation type, dependencies
- **Sortable Views**: Sort by various criteria

**Example:**
```python
browse_result = tracker.browse_fields()
# Returns all fields with statistics
```

### 4. Field Evaluation 🧮

Test field calculations with sample data:

- **Manual Entry**: Enter values for source fields
- **CSV Import**: Load data from CSV files
- **Excel Import**: Load data from Excel files (.xlsx, .xls)
- **Batch Evaluation**: Process multiple rows at once
- **Result Export**: Save results to CSV/Excel
- **Expression Testing**: Validate transformation logic

**Example:**
```python
# With CSV
df = evaluator.load_data_from_csv('data.csv', 'input_table')
result_df = evaluator.evaluate_with_dataframe('output_table', df)

# Manual
input_data = {'quantity': 10, 'price': 100}
result = evaluator.evaluate_field(field, input_data)
```

### 5. Visualization Support 📈

Export and visualize field lineage:

- **DOT Format Export**: Generate GraphViz DOT files
- **Directed Graph**: Fields as nodes, dependencies as edges
- **Online Visualization**: Use with GraphViz Online
- **Network Analysis**: Leverage NetworkX for graph queries
- **Custom Layouts**: Support for various visualization tools

**Example:**
```python
dot_graph = tracker.export_graph_dot()
# Visualize at: https://dreampuf.github.io/GraphvizOnline/
```

### 6. Dual Interface 💻

Use via web or command line:

#### Streamlit Web Application
- **Interactive UI**: Point-and-click interface
- **File Upload**: Upload SAS files directly
- **Live Updates**: See changes in real-time
- **Multiple Tabs**: Browse, Query, Evaluate, Visualize
- **Export Options**: Download results and graphs
- **Example Code**: Built-in examples

#### Command-Line Interface
- **Batch Processing**: Script multiple files
- **JSON Export**: Machine-readable output
- **Quick Queries**: Fast field lookups
- **Integration**: Use in pipelines and automation
- **Flexible Options**: Many command-line flags

### 7. Data Import/Export 📁

Comprehensive data handling:

- **Input Formats**: CSV, Excel (.xlsx, .xls)
- **Output Formats**: CSV, Excel, JSON, DOT
- **Large Files**: Efficient handling of big datasets
- **Multiple Sheets**: Excel sheet selection
- **Encoding Support**: Various character encodings

## SAS Language Support

### Supported Constructs

#### DATA Steps
- ✅ SET statements (single and multiple)
- ✅ MERGE statements with BY variables
- ✅ Field assignments
- ✅ Arithmetic operations (+, -, *, /)
- ✅ Basic functions (SUM, MEAN, MAX, MIN)
- ✅ WHERE clauses
- ✅ Field references (qualified and unqualified)

#### PROC Steps (Basic)
- ✅ PROC detection
- ✅ DATA= option
- ✅ OUT= option
- ⚠️  Limited transformation tracking

#### Expressions
- ✅ Arithmetic expressions
- ✅ Function calls
- ✅ Field references
- ✅ Constants
- ⚠️  Limited string operations
- ⚠️  No date/time functions yet

### Not Yet Supported

- ❌ Macro variables and expansion
- ❌ Complex PROC transformations
- ❌ Arrays and DO loops
- ❌ IF-THEN-ELSE logic in lineage
- ❌ FORMAT and INFORMAT statements
- ❌ RETAIN statements
- ❌ File inclusion (%INCLUDE)

## Advanced Features

### Graph Analysis

Built on NetworkX, supports:
- Shortest path finding
- Ancestor/descendant queries
- Connected components
- Topological sorting
- Cycle detection

```python
# Find all ancestors
ancestors = nx.ancestors(tracker.graph, "table.field")

# Shortest path
path = nx.shortest_path(tracker.graph, source, target)
```

### Metadata Support

Store custom metadata on fields:
```python
field.metadata = {
    'data_type': 'numeric',
    'business_owner': 'finance',
    'pii': False,
    'description': 'Total revenue calculation'
}
```

### Extensibility

Easy to extend:
- Custom parsers for new SAS constructs
- Custom operations in FieldOperationType
- Additional evaluators for complex functions
- Custom visualizations

## Performance

### Optimizations
- **Indexed Lookups**: O(1) field finding
- **Lazy Graph Building**: Build on demand
- **Efficient Storage**: Minimal memory footprint
- **Streaming Support**: Process large files

### Scalability
- Tested with programs containing 100+ fields
- Handles multiple data steps efficiently
- Graph algorithms scale well with NetworkX
- Memory efficient AST structure

## Use Cases

### 1. Impact Analysis
Understand which fields are affected when you change a source field:
```python
result = tracker.query_field('source_field')
downstream = result['results'][0]['downstream']
print(f"Changing this field affects {len(downstream)} other fields")
```

### 2. Data Quality
Trace data quality issues back to their source:
```python
path = tracker.get_lineage_path('source', 'problematic_field')
print("Data flows through:", " → ".join(path))
```

### 3. Documentation
Generate documentation of field transformations:
```python
for field in program.get_all_fields():
    print(f"{field.name}: {field.expression}")
    print(f"  Depends on: {[d.name for d in field.dependencies]}")
```

### 4. Testing
Validate calculations with known inputs:
```python
test_data = pd.read_csv('test_cases.csv')
results = evaluator.evaluate_with_dataframe('output', test_data)
assert results['expected'].equals(results['actual'])
```

### 5. Migration
Understand existing logic before migration:
```python
# Export all field definitions
for field in program.get_all_fields():
    print(f"-- Field: {field.name}")
    print(f"-- Definition: {field.expression}")
    print(f"-- SQL: {convert_to_sql(field.expression)}")
```

## Integration Examples

### With Jupyter Notebooks
```python
import pandas as pd
from sas_lineage.parser import SASParser
from sas_lineage.lineage import LineageTracker

# Parse and analyze
program = parser.parse(sas_code)
tracker = LineageTracker(program)

# Visualize in notebook
result = tracker.browse_fields()
pd.DataFrame(result['fields_by_table']['sales'])
```

### With Flask API
```python
@app.route('/lineage/<field_name>')
def get_lineage(field_name):
    result = tracker.query_field(field_name)
    return jsonify(result)
```

### With Airflow
```python
def analyze_sas_lineage(**context):
    parser = SASParser()
    program = parser.parse(sas_code)
    context['task_instance'].xcom_push(
        key='lineage',
        value=program.get_all_fields()
    )
```

## Future Enhancements

Planned features:
1. **Enhanced Parser**: Full macro support, more PROC steps
2. **Database Integration**: Connect to SAS servers
3. **Interactive Visualization**: D3.js-based graphs
4. **Version Comparison**: Compare lineage across versions
5. **Impact Scoring**: Quantify change impact
6. **Data Profiling**: Integrate with data quality metrics
7. **Export to Catalogs**: Integration with data catalogs
8. **Performance Monitoring**: Track query performance

## Best Practices

1. **Start Simple**: Test with small SAS files first
2. **Validate Results**: Check parsed fields match expectations
3. **Use Examples**: Learn from provided examples
4. **Iterate**: Build lineage incrementally
5. **Document**: Add metadata to important fields
6. **Test**: Validate calculations with known data
7. **Visualize**: Use graphs to understand complex lineage
8. **Export**: Save results for documentation

## Getting Help

- 📖 [README](../README.md) - Overview and installation
- 🚀 [Quick Start](../QUICKSTART.md) - Get started quickly
- 🌳 [AST Documentation](AST_DOCUMENTATION.md) - Understand the AST
- 💻 [API Usage](API_USAGE.md) - Programmatic usage
- 🤝 [Contributing](../CONTRIBUTING.md) - Contribute to the project
- 🐛 Issues - Report bugs on GitHub

## References

- [SAS Documentation](https://support.sas.com/)
- [NetworkX Documentation](https://networkx.org/)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [GraphViz](https://graphviz.org/)
- [Data Lineage Best Practices](https://en.wikipedia.org/wiki/Data_lineage)
