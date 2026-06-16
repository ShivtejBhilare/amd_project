@echo off
echo Starting CX Routing Engine Backend...
echo (Reload disabled due to native AMD ROCm LLM loading)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
pause
