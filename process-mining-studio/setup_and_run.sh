#!/usr/bin/env bash
# Quick-start script for Process Mining Studio
set -e

echo "=== Process Mining Studio Setup ==="
echo ""

# 1. Install Python dependencies
echo "[1/3] Installing Python dependencies..."
pip install -r requirements.txt

# 2. Check for graphviz system binary
echo ""
echo "[2/3] Checking graphviz system binary..."
if ! command -v dot &> /dev/null; then
    echo "  WARNING: graphviz system binary not found."
    echo "  The process map (DFG) will fall back to a table view."
    echo "  To install:"
    echo "    macOS:   brew install graphviz"
    echo "    Ubuntu:  sudo apt-get install graphviz"
    echo "    Windows: choco install graphviz"
else
    echo "  graphviz found: $(dot -V 2>&1 | head -1)"
fi

# 3. Launch app
echo ""
echo "[3/3] Launching Streamlit app..."
echo "  Open your browser at http://localhost:8501"
echo ""
streamlit run app.py
