# Quick Start Guide

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/alektebel/sas-field-lineage.git
   cd sas-field-lineage
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**
   
   **Linux/Mac:**
   ```bash
   chmod +x run.sh
   ./run.sh
   ```
   
   **Windows:**
   ```cmd
   run.bat
   ```
   
   **Or manually (only stdlib needed — no pip install required):**
   ```bash
   PYTHONPATH=src python -m sas_lineage.ui.server
   ```

## First Steps

### 1. Using the Web Explorer

Open http://127.0.0.1:8010 in your browser. The explorer:

1. **Renders the layered lineage graph** (golden sources → landing → curated →
   marts → reporting) with direction (↑ Upstream / ↕ Both / ↓ Downstream),
   hop depth, zoom/LOD, search and a register sidebar.
2. **Field trace** — click a dataset, then a field, for the complete trace from
   its golden sources (per-hop dataset, register, transform, merges).
3. **Value at every hop** — enter golden inputs (or upload a contract-cycle
   workbook), hit *Run value forward*, and watch the value propagate hop by hop
   across the graph.
4. **Live import** — use *Import SAS source* in the header to re-parse a `.sas`
   program and re-render the whole view.

### 2. Using the CLI

```bash
# Analyze a SAS file
python -m sas_lineage.cli examples/sales_analysis.sas

# Query a specific field
python -m sas_lineage.cli examples/sales_analysis.sas -q revenue

# Browse all fields
python -m sas_lineage.cli examples/sales_analysis.sas -b

# Export graph
python -m sas_lineage.cli examples/sales_analysis.sas -g lineage.dot
```

## Example Workflow

### Scenario: Analyzing Sales Data

1. **Create a SAS file** (or use `examples/sales_analysis.sas`):
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

2. **Upload to the web app** and explore:
   - See all fields in Browse tab
   - Query `profit` to trace its dependencies
   - Upload CSV data to evaluate calculations

3. **Or use CLI**:
   ```bash
   python -m sas_lineage.cli examples/sales_analysis.sas -q profit -t final_sales
   ```
   
   Output:
   ```
   ✅ Found 1 instance(s) of field 'profit'
   
   Instance 1: final_sales.profit
     Table: final_sales
     Operation: assignment
     Expression: net_revenue - cost
     Lineage Depth: 2
     ⬆️  Upstream: raw_sales.revenue, raw_sales.discount_amount, ...
     ⬇️  Downstream: (no dependencies)
   ```

## Testing Calculations

### Using CSV Input

1. Create a CSV file (`input.csv`):
   ```csv
   quantity,price,discount_rate,cost
   10,100,0.1,500
   20,150,0.15,1000
   ```

2. In the web app:
   - Go to "Evaluate Fields" tab
   - Upload the CSV
   - Click "Evaluate"
   - Download results

### Manual Entry

1. Enter values manually in the form
2. See calculated results instantly

## Visualizing Lineage

Export to DOT format and visualize:

```bash
python -m sas_lineage.cli examples/sales_analysis.sas -g output.dot
```

Then view at: https://dreampuf.github.io/GraphvizOnline/

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Check [examples/](examples/) for more SAS code samples
- Run tests: `python -m pytest tests/`

## Troubleshooting

**Issue**: Module not found errors
**Solution**: Make sure you're in the project root and install with `pip install -e .`

**Issue**: Streamlit won't start
**Solution**: Try `python -m streamlit run src/sas_lineage/ui/app.py` explicitly

**Issue**: No fields detected
**Solution**: Ensure your SAS code follows standard DATA step syntax with RUN; statements
