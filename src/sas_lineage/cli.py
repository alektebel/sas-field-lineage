"""
Command-line interface for SAS Field Lineage Tracker
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from .parser import SASParser
    from .analysis import build_table_report
except ImportError:
    from sas_lineage.parser import SASParser
    from sas_lineage.analysis import build_table_report


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="SAS Field Lineage Tracker - Analyze field-level data lineage in SAS code"
    )
    
    parser.add_argument(
        'sas_file',
        type=str,
        help='Path to SAS file to analyze'
    )
    
    parser.add_argument(
        '-q', '--query',
        type=str,
        help='Query for a specific field'
    )
    
    parser.add_argument(
        '-t', '--table',
        type=str,
        help='Table name (optional, for query)'
    )
    
    parser.add_argument(
        '-b', '--browse',
        action='store_true',
        help='Browse all fields'
    )
    
    parser.add_argument(
        '-g', '--graph',
        type=str,
        help='Export lineage graph to DOT file'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output file for results (JSON format)'
    )
    
    parser.add_argument(
        '--expand-macros',
        action='store_true',
        help='Expand the supported deterministic %%macro subset before parsing'
    )

    parser.add_argument(
        '--include-base',
        type=str,
        help='Sandbox directory for %%include (requires --expand-macros; reads below this directory only)'
    )

    parser.add_argument('--tables', action='store_true',
                        help='Emit an ordered table-resolution report as JSON, with diagnostics and dataset versions')
    parser.add_argument('--strict', action='store_true',
                        help='With --tables, exit 2 when analysis is partial (the JSON report is still emitted)')
    parser.add_argument('--default-library',
                        help='Explicit logical library for one-level names in --tables (no default is assumed)')

    args = parser.parse_args()
    if args.tables and (args.query or args.browse or args.graph):
        parser.error('--tables cannot be combined with --query, --browse or --graph')
    if (args.strict or args.default_library) and not args.tables:
        parser.error('--strict and --default-library require --tables')
    
    # Read SAS file
    sas_file_path = Path(args.sas_file)
    if not sas_file_path.exists():
        print(f"Error: File '{args.sas_file}' not found", file=sys.stderr)
        return 1
    
    try:
        sas_code = sas_file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as error:
        print(f'Error reading {sas_file_path}: {error}', file=sys.stderr)
        return 1
    
    # Parse SAS code
    if not args.tables:
        print(f"Parsing {args.sas_file}...")
    expand = args.expand_macros or bool(args.include_base)
    include_base = args.include_base if expand else None
    parser_obj = SASParser()
    program = parser_obj.parse(sas_code, expand_macros=expand, include_base=include_base)
    if args.tables:
        try:
            result = build_table_report(program, str(sas_file_path), args.default_library)
        except ValueError as error:
            parser.error(str(error))
        rendered = json.dumps(result, indent=2)
        print(rendered)
        if args.output:
            try:
                Path(args.output).write_text(rendered + '\n', encoding='utf-8')
            except OSError as error:
                print(f'Error writing report: {error}', file=sys.stderr)
                return 1
        return 2 if args.strict and result['status'] == 'partial' else 0

    # Table reports need only the standard library; field evaluation has
    # optional pandas/networkx dependencies loaded by the lineage package.
    if __package__:
        from .lineage import LineageTracker
    else:
        from sas_lineage.lineage import LineageTracker
    tracker = LineageTracker(program)
    
    print(f"Found {len(program.get_all_fields())} fields in {len(program.data_steps)} data steps")
    print()
    
    # Execute requested operation
    result = None
    
    if args.query:
        # Query for a field
        result = tracker.query_field(args.query, args.table)
        print_query_result(result)
    
    elif args.browse:
        # Browse all fields
        result = tracker.browse_fields(args.table)
        print_browse_result(result)
    
    elif args.graph:
        # Export graph
        dot_graph = tracker.export_graph_dot()
        with open(args.graph, 'w') as f:
            f.write(dot_graph)
        print(f"Graph exported to {args.graph}")
        result = {"graph_file": args.graph}
    
    else:
        # Default: show summary
        result = tracker.browse_fields()
        print_summary(result)
    
    # Save output if requested
    if args.output and result:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to {args.output}")
    
    return 0


def print_query_result(result):
    """Print query result to console"""
    if not result['found']:
        print(f"❌ Field '{result['field_name']}' not found")
        return
    
    print(f"✅ Found {result['count']} instance(s) of field '{result['field_name']}'")
    print()
    
    for idx, res in enumerate(result['results']):
        print(f"Instance {idx + 1}: {res['node_id']}")
        print(f"  Table: {res['field']['table']}")
        print(f"  Operation: {res['field']['operation']}")
        if res['field']['expression']:
            print(f"  Expression: {res['field']['expression']}")
        print(f"  Lineage Depth: {res['depth']}")
        
        if res['upstream']:
            print(f"  ⬆️  Upstream: {', '.join(res['upstream'])}")
        else:
            print("  ⬆️  Upstream: (source field)")
        
        if res['downstream']:
            print(f"  ⬇️  Downstream: {', '.join(res['downstream'])}")
        else:
            print("  ⬇️  Downstream: (no dependencies)")
        
        print()


def print_browse_result(result):
    """Print browse result to console"""
    stats = result['stats']
    print("📊 Field Statistics:")
    print(f"  Total Fields: {stats['total_fields']}")
    print(f"  Total Tables: {stats['total_tables']}")
    print(f"  Fields with Dependencies: {stats['fields_with_dependencies']}")
    print(f"  Max Lineage Depth: {stats['max_depth']}")
    print()
    
    print("📋 Fields by Table:")
    for table_name, fields in result['fields_by_table'].items():
        print(f"\n  {table_name} ({len(fields)} fields):")
        for field in fields:
            deps = f" <- {', '.join(field['dependencies'])}" if field['dependencies'] else ""
            print(f"    - {field['name']}{deps}")


def print_summary(result):
    """Print summary to console"""
    stats = result['stats']
    print("=" * 60)
    print("SAS Field Lineage Summary")
    print("=" * 60)
    print(f"Total Fields:              {stats['total_fields']}")
    print(f"Total Tables:              {stats['total_tables']}")
    print(f"Fields with Dependencies:  {stats['fields_with_dependencies']}")
    print(f"Max Lineage Depth:         {stats['max_depth']}")
    print("=" * 60)
    print()
    print("Tables:", ", ".join(result['all_tables']))
    print()
    print("Use -q/--query to search for a specific field")
    print("Use -b/--browse to see all fields")
    print("Use -g/--graph to export lineage graph")


if __name__ == "__main__":
    sys.exit(main())
