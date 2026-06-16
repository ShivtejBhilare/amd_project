@echo off
echo Starting vLLM OpenAI-Compatible Server for AMD CX Routing Engine...
echo This utilizes ROCm for AMD GPU acceleration.

set MODEL_NAME=%1
if "%MODEL_NAME%"=="" set MODEL_NAME=meta-llama/Llama-3-8b-instruct

echo Using model: %MODEL_NAME%
python -m vllm.entrypoints.openai.api_server --model %MODEL_NAME% --port 8000 --host 0.0.0.0
