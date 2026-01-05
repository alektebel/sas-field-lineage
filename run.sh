#!/bin/bash
# Quick start script for SAS Field Lineage Tracker

echo "🔍 SAS Field Lineage Tracker"
echo "=============================="
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✅ Python found: $(python3 --version)"
echo ""

# Check if dependencies are installed
if ! python3 -c "import streamlit" 2> /dev/null; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
    echo ""
fi

# Launch Streamlit app
echo "🚀 Launching Streamlit application..."
echo "   The app will open in your browser at http://localhost:8501"
echo ""
echo "   Press Ctrl+C to stop the server"
echo ""

python3 -m streamlit run src/sas_lineage/ui/app.py
