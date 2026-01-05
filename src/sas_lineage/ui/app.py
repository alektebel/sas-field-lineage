"""
Streamlit web application for SAS Field Lineage Tracker
"""
import streamlit as st
import pandas as pd
from io import StringIO
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sas_lineage.parser import SASParser
from sas_lineage.lineage import LineageTracker, FieldEvaluator
from sas_lineage.ast import SASProgram


def main():
    st.set_page_config(
        page_title="SAS Field Lineage Tracker",
        page_icon="🔍",
        layout="wide"
    )
    
    st.title("🔍 SAS Field Lineage Tracker")
    st.markdown("""
    Track field-level data lineage in SAS code. Upload SAS code to analyze field dependencies,
    query specific fields, browse all fields, and evaluate field values with sample data.
    """)
    
    # Sidebar for SAS code input
    with st.sidebar:
        st.header("📄 SAS Code Input")
        
        input_method = st.radio(
            "Choose input method:",
            ["Upload File", "Paste Code", "Use Example"]
        )
        
        sas_code = None
        
        if input_method == "Upload File":
            uploaded_file = st.file_uploader(
                "Upload SAS file (.sas)", 
                type=['sas', 'txt']
            )
            if uploaded_file:
                sas_code = uploaded_file.read().decode('utf-8')
        
        elif input_method == "Paste Code":
            sas_code = st.text_area(
                "Paste SAS code here:",
                height=300,
                placeholder="DATA output;\n  SET input;\n  new_field = old_field * 2;\nRUN;"
            )
        
        else:  # Use Example
            sas_code = get_example_sas_code()
            st.code(sas_code, language='sas')
    
    # Main area
    if sas_code:
        # Parse the SAS code
        with st.spinner("Parsing SAS code..."):
            parser = SASParser()
            program = parser.parse(sas_code)
            tracker = LineageTracker(program)
            evaluator = FieldEvaluator(program)
        
        # Store in session state
        st.session_state['program'] = program
        st.session_state['tracker'] = tracker
        st.session_state['evaluator'] = evaluator
        
        # Create tabs for different functionalities
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Browse Fields", 
            "🔍 Query Field", 
            "🧮 Evaluate Fields",
            "📈 Lineage Graph"
        ])
        
        with tab1:
            show_browse_fields(tracker)
        
        with tab2:
            show_query_field(tracker)
        
        with tab3:
            show_evaluate_fields(evaluator, program)
        
        with tab4:
            show_lineage_graph(tracker)
    
    else:
        st.info("👈 Please provide SAS code using the sidebar to get started.")


def show_browse_fields(tracker: LineageTracker):
    """Display browse fields functionality"""
    st.header("Browse All Fields")
    
    browse_result = tracker.browse_fields()
    
    # Show statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Fields", browse_result['stats']['total_fields'])
    with col2:
        st.metric("Total Tables", browse_result['stats']['total_tables'])
    with col3:
        st.metric("Fields with Dependencies", browse_result['stats']['fields_with_dependencies'])
    with col4:
        st.metric("Max Lineage Depth", browse_result['stats']['max_depth'])
    
    st.divider()
    
    # Filter by table
    all_tables = browse_result['all_tables']
    selected_table = st.selectbox(
        "Filter by table:",
        ["All Tables"] + sorted(all_tables)
    )
    
    # Display fields
    if selected_table == "All Tables":
        for table_name, fields in browse_result['fields_by_table'].items():
            with st.expander(f"📋 Table: {table_name} ({len(fields)} fields)", expanded=True):
                display_fields_table(fields)
    else:
        fields = browse_result['fields_by_table'].get(selected_table, [])
        st.subheader(f"Fields in {selected_table}")
        display_fields_table(fields)


def display_fields_table(fields):
    """Display fields in a table format"""
    if not fields:
        st.info("No fields found.")
        return
    
    df_data = []
    for field in fields:
        df_data.append({
            "Field Name": field['name'],
            "Operation": field['operation'] or "N/A",
            "Expression": field['expression'] or "N/A",
            "Dependencies": ", ".join(field['dependencies']) if field['dependencies'] else "None",
            "Line": field['source_line'] or "N/A"
        })
    
    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True)


def show_query_field(tracker: LineageTracker):
    """Display query field functionality"""
    st.header("Query Specific Field")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        field_name = st.text_input("Field name:", placeholder="e.g., total_sales")
    
    with col2:
        table_name = st.text_input("Table name (optional):", placeholder="e.g., output")
    
    if st.button("🔍 Search", type="primary"):
        if field_name:
            table = table_name if table_name else None
            result = tracker.query_field(field_name, table)
            
            if result['found']:
                st.success(f"Found {result['count']} instance(s) of field '{field_name}'")
                
                for idx, res in enumerate(result['results']):
                    with st.expander(f"Instance {idx + 1}: {res['node_id']}", expanded=True):
                        field_info = res['field']
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.write("**Table:**", field_info['table'] or "N/A")
                        with col2:
                            st.write("**Operation:**", field_info['operation'] or "N/A")
                        with col3:
                            st.write("**Lineage Depth:**", res['depth'])
                        
                        if field_info['expression']:
                            st.write("**Expression:**")
                            st.code(field_info['expression'], language='sas')
                        
                        if res['upstream']:
                            st.write("**⬆️ Upstream Dependencies:**")
                            st.write(", ".join(res['upstream']))
                        else:
                            st.info("No upstream dependencies (source field)")
                        
                        if res['downstream']:
                            st.write("**⬇️ Downstream Dependencies:**")
                            st.write(", ".join(res['downstream']))
                        else:
                            st.info("No downstream dependencies")
            else:
                st.error(f"Field '{field_name}' not found")
        else:
            st.warning("Please enter a field name")


def show_evaluate_fields(evaluator: FieldEvaluator, program: SASProgram):
    """Display field evaluation functionality"""
    st.header("Evaluate Fields with Sample Data")
    
    st.markdown("""
    Manually enter field values or upload CSV/Excel files to see how output fields are calculated.
    """)
    
    # Input method selection
    input_method = st.radio(
        "Data input method:",
        ["Manual Entry", "Upload CSV", "Upload Excel"],
        horizontal=True
    )
    
    input_data = None
    
    if input_method == "Manual Entry":
        st.subheader("Enter Field Values")
        
        # Get all source fields (fields without expressions)
        all_fields = program.get_all_fields()
        source_fields = [f for f in all_fields if not f.expression or not f.dependencies]
        
        if source_fields:
            input_data = {}
            cols = st.columns(2)
            for idx, field in enumerate(source_fields[:10]):  # Limit to 10 fields
                col = cols[idx % 2]
                with col:
                    value = st.text_input(
                        f"{field.table or 'input'}.{field.name}",
                        key=f"field_{idx}"
                    )
                    if value:
                        try:
                            input_data[field.name] = float(value) if '.' in value else int(value)
                        except ValueError:
                            input_data[field.name] = value
        else:
            st.info("No source fields found in the SAS code.")
    
    elif input_method == "Upload CSV":
        csv_file = st.file_uploader("Upload CSV file", type=['csv'])
        if csv_file:
            input_data = pd.read_csv(csv_file)
            st.write("**Preview of uploaded data:**")
            st.dataframe(input_data.head(), use_container_width=True)
    
    else:  # Upload Excel
        excel_file = st.file_uploader("Upload Excel file", type=['xlsx', 'xls'])
        if excel_file:
            input_data = pd.read_excel(excel_file)
            st.write("**Preview of uploaded data:**")
            st.dataframe(input_data.head(), use_container_width=True)
    
    # Evaluate button
    if input_data is not None and st.button("🧮 Evaluate", type="primary"):
        st.subheader("Evaluation Results")
        
        if isinstance(input_data, dict):
            # Manual entry - evaluate each calculated field
            calculated_fields = [f for f in program.get_all_fields() if f.expression]
            
            if calculated_fields:
                results = []
                for field in calculated_fields:
                    result = evaluator.evaluate_field(field, input_data)
                    results.append({
                        "Field": f"{field.table or 'output'}.{field.name}",
                        "Expression": field.expression,
                        "Result": result
                    })
                
                df_results = pd.DataFrame(results)
                st.dataframe(df_results, use_container_width=True)
            else:
                st.info("No calculated fields found.")
        
        elif isinstance(input_data, pd.DataFrame):
            # DataFrame input - evaluate for all rows
            if program.data_steps:
                table_name = program.data_steps[0].output_table
                result_df = evaluator.evaluate_with_dataframe(table_name, input_data)
                
                st.write("**Results:**")
                st.dataframe(result_df, use_container_width=True)
                
                # Download button
                csv = result_df.to_csv(index=False)
                st.download_button(
                    "⬇️ Download Results as CSV",
                    csv,
                    "evaluated_results.csv",
                    "text/csv"
                )
            else:
                st.warning("No data steps found in the SAS code.")


def show_lineage_graph(tracker: LineageTracker):
    """Display lineage graph"""
    st.header("Field Lineage Graph")
    
    st.markdown("""
    Visual representation of field dependencies in DOT format (GraphViz).
    """)
    
    try:
        dot_graph = tracker.export_graph_dot()
        
        # Display as code
        st.code(dot_graph, language='dot')
        
        st.info("""
        💡 **Tip:** Copy the DOT code above and paste it into an online GraphViz viewer 
        (e.g., https://dreampuf.github.io/GraphvizOnline/) to visualize the lineage graph.
        """)
        
        # Download button
        st.download_button(
            "⬇️ Download DOT file",
            dot_graph,
            "lineage_graph.dot",
            "text/plain"
        )
        
    except Exception as e:
        st.error(f"Error generating graph: {str(e)}")


def get_example_sas_code() -> str:
    """Return example SAS code"""
    return """/* Example SAS Code - Sales Analysis */

DATA raw_sales;
    SET input_data;
    revenue = quantity * price;
    discount_amount = revenue * discount_rate;
RUN;

DATA final_sales;
    SET raw_sales;
    net_revenue = revenue - discount_amount;
    profit = net_revenue - cost;
    profit_margin = profit / net_revenue;
RUN;

DATA summary;
    SET final_sales;
    total_profit = SUM(profit);
    avg_margin = MEAN(profit_margin);
RUN;
"""


if __name__ == "__main__":
    main()
