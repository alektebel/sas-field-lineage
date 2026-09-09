#!/bin/bash
# Quick start script for the SAS Field Lineage Explorer web app.
# The explorer is a zero-dependency (stdlib-only) web server + faithful web UI.
# The legacy Streamlit app is still available at src/sas_lineage/ui/app.py.

echo "🔍 Field Lineage & Golden Source Explorer"
echo "=========================================="
echo ""

# Check Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✅ Python found: $(python3 --version)"
echo ""

# The explorer needs only the standard library + the bundled parser (networkx is
# optional and already vendored functionality). It does NOT need streamlit.
echo "🚀 Launching web explorer..."
echo "   Open http://127.0.0.1:8010 in your browser"
echo "   Press Ctrl+C to stop"
echo ""

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m sas_lineage.ui.server "$@"
