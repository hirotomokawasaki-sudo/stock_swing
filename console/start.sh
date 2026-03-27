#!/bin/bash
# Start Stock Swing Web Console

cd "$(dirname "$0")"

echo "🤖 Starting Stock Swing Console..."
echo ""

# Check if venv exists
if [ ! -d "../venv" ]; then
    echo "❌ Virtual environment not found at ../venv"
    echo "   Please create it first: python3 -m venv ../venv"
    exit 1
fi

# Activate venv and use it explicitly
source ../venv/bin/activate

# Check dependencies
if ! python -c "import yaml" 2>/dev/null; then
    echo "⚠️  Missing dependencies. Installing..."
    pip install -q PyYAML
fi

# Start server using venv python
echo "✅ Starting console server..."
echo "   Using Python: $(which python)"
python app.py
