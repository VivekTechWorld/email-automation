#!/bin/bash
set -e

echo "=========================================="
echo " Auto Email Reply System - Setup Script"
echo "=========================================="

# ── 1. Install Ollama ──────────────────────────────────────────────
echo ""
echo "[1/5] Installing Ollama..."
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
    echo "Ollama installed."
else
    echo "Ollama already installed: $(ollama --version)"
fi

# ── 2. Start Ollama service ───────────────────────────────────────
echo ""
echo "[2/5] Starting Ollama service..."
if ! pgrep -x "ollama" > /dev/null; then
    ollama serve &>/dev/null &
    sleep 3
    echo "Ollama service started."
else
    echo "Ollama already running."
fi

# ── 3. Pull models ────────────────────────────────────────────────
echo ""
echo "[3/5] Pulling LLM model (llama3.2:3b)..."
echo "      This will take 5-10 minutes on first run."
ollama pull llama3.2:3b

echo ""
echo "      Pulling embedding model (nomic-embed-text)..."
ollama pull nomic-embed-text

echo "Models ready."

# ── 4. Python virtual environment ────────────────────────────────
echo ""
echo "[4/5] Setting up Python environment..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

PYTHON_BIN="${PYTHON:-$(command -v python3.12 || command -v python3 || command -v python)}"
if [ -z "$PYTHON_BIN" ]; then
    echo "Error: Python is required but not found in PATH."
    exit 1
fi
echo "Using Python: $($PYTHON_BIN --version)"
$PYTHON_BIN -m venv venv
source venv/bin/activate

pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "Python environment ready."

# ── 5. Create .env if not exists ─────────────────────────────────
echo ""
echo "[5/5] Setting up configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ".env created from .env.example — edit it before starting."
else
    echo ".env already exists."
fi

echo ""
echo "=========================================="
echo " Setup Complete!"
echo "=========================================="
echo ""
echo " To start the backend:"
echo "   cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000"
echo ""
echo " To ingest knowledge base documents:"
echo "   curl -X POST http://localhost:8000/ingest"
echo ""
echo " Then import n8n/email_flow_clean.json into n8n (http://localhost:5678)"
echo ""
