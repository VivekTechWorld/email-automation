#!/bin/bash
# ============================================================
# Local CPU Fine-tuning — wrapper script
#
# Uses: Python transformers + peft (LoRA)
# Model: TinyLlama 1.1B (fast on CPU, ~3-5 hours)
#
# Usage:
#   cd finetune/
#   ./finetune_local.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

echo "============================================"
echo " Local CPU Fine-tuning Pipeline"
echo "============================================"
echo ""

# ── Step 1: Activate venv ────────────────────────────────────────
source "$BACKEND_DIR/venv/bin/activate"

# ── Step 2: Install fine-tuning dependencies ────────────────────
echo "[1/3] Installing fine-tuning dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements_finetune.txt"
echo "  Done."

# ── Step 3: Prepare dataset ──────────────────────────────────────
echo ""
echo "[2/3] Preparing dataset..."
python3 "$SCRIPT_DIR/prepare_dataset.py"

# ── Step 4: Run training ─────────────────────────────────────────
echo ""
echo "[3/3] Starting LoRA fine-tuning on CPU..."
echo "      Expected time: 3-5 hours. Loss should decrease each epoch."
echo "      Output: data/finetuned/final_model"
echo ""
python3 "$SCRIPT_DIR/finetune_cpu.py"

echo ""
echo "============================================"
echo " Training done!"
echo " Next: run the conversion script"
echo "   python3 finetune/convert_to_ollama.py"
echo "============================================"
