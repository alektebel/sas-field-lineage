# SAS Field Lineage Tracker 🔍

A Python application for tracking field-level data lineage in SAS code. This tool helps you understand how fields are created, transformed, and flow through your SAS programs by building an Abstract Syntax Tree (AST) representation of field dependencies.

## Features

- **🌳 AST Representation**: Fields are represented using an Abstract Syntax Tree (AST) showing their dependencies and relationships
- **🔍 Query Functionality**: Search for specific fields and trace their lineage upstream and downstream
- **📊 Browse Fields**: Explore all fields in your SAS program with filtering and grouping by table
- **🧮 Field Evaluation**: Manually enter field values or upload CSV/Excel files to see calculated outputs
- **📈 Visualization**: Export field lineage graphs in DOT format for GraphViz visualization
- **💻 Dual Interface**: Use via Streamlit web app or command-line interface
- **📁 Data Import**: Read input data from Excel (.xlsx, .xls) and CSV files

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Install from source

```bash
# Clone the repository
git clone https://github.com/alektebel/sas-field-lineage.git
cd sas-field-lineage

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

## Usage

### Streamlit Web Application

Launch the interactive web interface:

```bash
streamlit run src/sas_lineage/ui/app.py
```

Or using Python:

```bash
python -m streamlit run src/sas_lineage/ui/app.py
```

The web application provides four main tabs:

1. **📊 Browse Fields**: View all fields grouped by table with statistics
2. **🔍 Query Field**: Search for specific fields and view their lineage
3. **🧮 Evaluate Fields**: Input sample data to see calculated field values
4. **📈 Lineage Graph**: Export and visualize field dependency graphs

### Command-Line Interface

Use the CLI for batch processing and scripting:

```bash
# Show summary of a SAS file
sas-lineage examples/sales_analysis.sas

# Query for a specific field
sas-lineage examples/sales_analysis.sas -q revenue

# Query with table name
sas-lineage examples/sales_analysis.sas -q profit -t final_sales

# Browse all fields
sas-lineage examples/sales_analysis.sas -b

# Export lineage graph
sas-lineage examples/sales_analysis.sas -g output.dot

# Save results to JSON
sas-lineage examples/sales_analysis.sas -b -o results.json
```

## How It Works

### 1. Parsing

The SAS parser reads your SAS code and identifies:
- DATA steps with input/output tables
- Field assignments and calculations
- SET, MERGE, and BY statements
- Field dependencies and transformations

### 2. AST Construction

Each field is represented as a `FieldNode` in an AST that contains:
- Field name and table
- Operation type (assignment, calculation, function, etc.)
- Expression/formula
- List of dependent fields
- Source line number
- Metadata

### 3. Lineage Tracking

The `LineageTracker` builds a directed graph where:
- Nodes represent fields
- Edges represent dependencies
- Paths show how data flows through transformations

### 4. Field Evaluation

The `FieldEvaluator` allows you to:
- Provide sample input data
- Calculate derived field values
- Test transformations with real data

## Example

Given this SAS code:

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

The tool creates an AST showing:
- `revenue` depends on `quantity` and `price`
- `discount_amount` depends on `revenue` and `discount_rate`
- `net_revenue` depends on `revenue` and `discount_amount`
- `profit` depends on `net_revenue` and `cost`

## Architecture

```
src/sas_lineage/
├── ast/            # AST data structures for field representation
│   └── field_ast.py
├── parser/         # SAS code parser
│   └── sas_parser.py
├── lineage/        # Lineage tracking and evaluation
│   ├── tracker.py
│   └── evaluator.py
├── ui/             # Streamlit web interface
│   └── app.py
├── utils/          # Helper utilities
│   └── helpers.py
└── cli.py          # Command-line interface
```

## Data Structures

### FieldNode

Represents a single field with its metadata and dependencies:

```python
@dataclass
class FieldNode:
    name: str                           # Field name
    table: Optional[str]                # Table name
    operation: Optional[FieldOperationType]  # Operation type
    expression: Optional[str]           # SAS expression
    dependencies: List[FieldNode]       # Dependent fields
    source_line: Optional[int]          # Line number in source
    metadata: Dict[str, Any]            # Additional metadata
```

### SASProgram

Container for all data steps and fields in a SAS program:

```python
class SASProgram:
    data_steps: List[DataStepNode]      # All DATA steps
    proc_steps: List[ProcStepNode]      # All PROC steps
    all_fields: Dict[str, List[FieldNode]]  # Indexed fields
```

## Supported SAS Constructs

Currently supports:
- DATA steps with SET and MERGE statements
- Field assignments and calculations
- BY variables for merging
- Basic arithmetic operations
- Common SAS functions (SUM, MEAN, MAX, MIN)

## Limitations

This is a simplified SAS parser focusing on field lineage. It does not:
- Fully parse all SAS syntax (use for common patterns)
- Execute SAS code or connect to SAS servers
- Handle complex macro logic
- Support all SAS procedures

For production use, consider integrating with SAS metadata servers or using official SAS lineage tools.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## References

- [SAS Documentation](https://support.sas.com/)
- [ANTLR](https://www.antlr.org/) - Parser generator (future integration)
- Open-source SAS parsers on GitHub

## License

MIT License - See LICENSE file for details
