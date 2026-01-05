#!/usr/bin/env python3
"""
Demo script showing how to use the SAS Field Lineage Tracker API
"""

from sas_lineage.parser import SASParser
from sas_lineage.lineage import LineageTracker, FieldEvaluator
import pandas as pd
from pathlib import Path


def demo_basic_parsing():
    """Demonstrate basic SAS code parsing"""
    print("=" * 60)
    print("Demo 1: Basic Parsing")
    print("=" * 60)
    
    sas_code = """
    DATA sales;
        SET input;
        revenue = quantity * price;
        profit = revenue - cost;
    RUN;
    """
    
    parser = SASParser()
    program = parser.parse(sas_code)
    
    print(f"✓ Parsed {len(program.data_steps)} data step(s)")
    print(f"✓ Found {len(program.get_all_fields())} field(s)")
    
    for field in program.get_all_fields():
        print(f"  - {field.name}: {field.expression}")
    print()


def demo_lineage_tracking():
    """Demonstrate lineage tracking"""
    print("=" * 60)
    print("Demo 2: Lineage Tracking")
    print("=" * 60)
    
    # Load example file
    example_file = Path('examples/sales_analysis.sas')
    with open(example_file, 'r') as f:
        sas_code = f.read()
    
    parser = SASParser()
    program = parser.parse(sas_code)
    tracker = LineageTracker(program)
    
    # Query a field
    print("\nQuerying field 'profit'...")
    result = tracker.query_field('profit')
    
    if result['found']:
        for res in result['results']:
            print(f"\n✓ Found: {res['node_id']}")
            print(f"  Expression: {res['field']['expression']}")
            print(f"  Upstream dependencies: {', '.join(res['upstream'][:3])}...")
            print(f"  Lineage depth: {res['depth']}")
    print()


def demo_browse_fields():
    """Demonstrate browsing all fields"""
    print("=" * 60)
    print("Demo 3: Browse Fields")
    print("=" * 60)
    
    example_file = Path('examples/sales_analysis.sas')
    with open(example_file, 'r') as f:
        sas_code = f.read()
    
    parser = SASParser()
    program = parser.parse(sas_code)
    tracker = LineageTracker(program)
    
    result = tracker.browse_fields()
    
    print(f"\n✓ Total fields: {result['stats']['total_fields']}")
    print(f"✓ Total tables: {result['stats']['total_tables']}")
    print(f"✓ Max lineage depth: {result['stats']['max_depth']}")
    
    print("\nTables found:")
    for table in result['all_tables']:
        print(f"  - {table}")
    print()


def demo_field_evaluation():
    """Demonstrate field evaluation"""
    print("=" * 60)
    print("Demo 4: Field Evaluation")
    print("=" * 60)
    
    sas_code = """
    DATA output;
        SET input;
        total = quantity * price;
        discount = total * 0.1;
        final = total - discount;
    RUN;
    """
    
    parser = SASParser()
    program = parser.parse(sas_code)
    evaluator = FieldEvaluator(program)
    
    # Manual evaluation
    print("\nManual value evaluation:")
    input_data = {'quantity': 10, 'price': 50}
    
    for field in program.get_all_fields():
        if field.expression:
            result = evaluator.evaluate_field(field, input_data)
            print(f"  {field.name} = {result}")
    
    # CSV evaluation
    csv_file = Path('examples/sample_data.csv')
    if csv_file.exists():
        print("\nEvaluating with CSV data:")
        df = pd.read_csv(csv_file)
        print(f"✓ Loaded {len(df)} rows from CSV")
        print(f"  Columns: {', '.join(df.columns)}")
    print()


def demo_graph_export():
    """Demonstrate graph export"""
    print("=" * 60)
    print("Demo 5: Graph Export")
    print("=" * 60)
    
    example_file = Path('examples/sales_analysis.sas')
    with open(example_file, 'r') as f:
        sas_code = f.read()
    
    parser = SASParser()
    program = parser.parse(sas_code)
    tracker = LineageTracker(program)
    
    # Export graph
    dot_graph = tracker.export_graph_dot()
    
    output_file = '/tmp/demo_lineage.dot'
    with open(output_file, 'w') as f:
        f.write(dot_graph)
    
    print(f"\n✓ Exported lineage graph to {output_file}")
    print(f"✓ Graph contains {tracker.graph.number_of_nodes()} nodes")
    print(f"✓ Graph contains {tracker.graph.number_of_edges()} edges")
    print("\nVisualize at: https://dreampuf.github.io/GraphvizOnline/")
    print()


def demo_complex_analysis():
    """Demonstrate complex field analysis"""
    print("=" * 60)
    print("Demo 6: Complex Analysis")
    print("=" * 60)
    
    example_file = Path('examples/complex_employee_analysis.sas')
    if not example_file.exists():
        print("Complex example file not found, skipping...")
        return
    
    with open(example_file, 'r') as f:
        sas_code = f.read()
    
    parser = SASParser()
    program = parser.parse(sas_code)
    tracker = LineageTracker(program)
    
    print(f"\n✓ Parsed complex SAS program")
    print(f"  Data steps: {len(program.data_steps)}")
    print(f"  Total fields: {len(program.get_all_fields())}")
    
    # Find fields with most dependencies
    fields_with_deps = [
        (f, len(f.dependencies)) 
        for f in program.get_all_fields() 
        if f.dependencies
    ]
    fields_with_deps.sort(key=lambda x: x[1], reverse=True)
    
    print("\nFields with most dependencies:")
    for field, count in fields_with_deps[:5]:
        print(f"  {field.table}.{field.name}: {count} dependencies")
    
    # Lineage depth analysis
    depths = {}
    for field in program.get_all_fields():
        depth = tracker._calculate_lineage_depth(field)
        depths[depth] = depths.get(depth, 0) + 1
    
    print("\nLineage depth distribution:")
    for depth in sorted(depths.keys()):
        print(f"  Depth {depth}: {depths[depth]} fields")
    print()


def main():
    """Run all demos"""
    print("\n" + "=" * 60)
    print("SAS Field Lineage Tracker - API Demo")
    print("=" * 60 + "\n")
    
    try:
        demo_basic_parsing()
        demo_lineage_tracking()
        demo_browse_fields()
        demo_field_evaluation()
        demo_graph_export()
        demo_complex_analysis()
        
        print("=" * 60)
        print("All demos completed successfully! ✓")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error running demo: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
