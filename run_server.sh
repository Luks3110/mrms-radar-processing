#!/bin/bash
# Simple script to run the development server

echo "🚀 Starting MRMS Radar API server..."
echo ""
echo "📍 API will be available at: http://localhost:8000"
echo "📖 API docs at: http://localhost:8000/docs"
echo "🏥 Health check at: http://localhost:8000/health"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Check if virtual environment is activated
if [[ -z "${VIRTUAL_ENV}" ]]; then
    echo "⚠️  Warning: Virtual environment not activated"
    echo "   Run: source .venv/bin/activate"
    echo ""
fi

# Run the server
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000

