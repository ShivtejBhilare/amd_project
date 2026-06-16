# CX Routing Engine

A native multi-agent AI routing system with Developer Copilot and Customer tracking, running entirely locally on AMD ROCm using HuggingFace `transformers` and `langchain`.

## Features
- **Native AMD Inference**: Uses `Qwen2.5-14B-Instruct` natively on GPU without relying on external APIs.
- **Agentic Routing**: A Supervisor AI automatically triages customer tickets to the correct developer based on context.
- **Developer Copilot**: A built-in AI Copilot to help developers update ticket status and communicate securely with customers.
- **Customer Dashboard**: Track timeline updates of escalated tickets in real time.

## Linux Setup & Execution

### Prerequisites
1. Python 3.10+
2. AMD ROCm drivers installed
3. Git

### Installation
Clone the repository:
```bash
git clone <your-repo-url>
cd cx_routing_engine
```

Install the required Python packages:
```bash
pip install -r requirements.txt
```
*(Note: If you have an `requirements.txt`, ensure you have torch, transformers, langchain, langchain-huggingface, accelerate installed).*

### Running the Application

Since the backend serves the frontend natively through FastAPI, you only need to run a single script!

Make the script executable:
```bash
chmod +x run_backend.sh
```

Run the server:
```bash
./run_backend.sh
```

The application will now be available at **http://localhost:8001**.

### Notes on AI Initialization
The very first chat message you send will trigger the local AI lazy-loading process. Depending on your internet connection and disk speed, it may take a few minutes to download the 28GB model and load it into your AMD GPU's VRAM. Successive messages will be instantaneous.
