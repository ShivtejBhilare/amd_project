#!/bin/bash
echo "Starting FastAPI Backend and Web Server..."
echo "Ensure you have activated your virtual environment and installed requirements.txt"

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
