"""
Converts the fine-tuned model to GGUF format and loads it into Ollama.

Requirements: cmake + llama.cpp (auto-installed by this script)

Usage:
    python convert_to_ollama.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

BASE_DIR     = Path(__file__).parent.parent
ADAPTER_DIR  = BASE_DIR / "data" / "finetuned" / "final_model"   # LoRA adapter
MERGED_DIR   = BASE_DIR / "data" / "finetuned" / "merged_model"  # merged full model
OUTPUT_DIR   = BASE_DIR / "data" / "finetuned"
LLAMA_DIR    = BASE_DIR / "llama.cpp"
GGUF_OUTPUT  = OUTPUT_DIR / "email-support.gguf"
MODEL_NAME   = "email-support"
BASE_MODEL   = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"


def run(cmd: str, cwd=None):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        print(f"ERROR: command failed with exit code {result.returncode}")
        sys.exit(1)


def quote(path: Path) -> str:
    return f'"{path}"'


def merge_lora_into_base():
    """Merges the LoRA adapter with the base model into a full HuggingFace model."""
    if MERGED_DIR.exists() and (MERGED_DIR / "config.json").exists():
        print(f"Merged model already exists at {MERGED_DIR}, skipping merge.")
        return

    print(f"\nMerging LoRA adapter into base model ({BASE_MODEL})...")
    print("  This downloads ~2GB on first run and takes ~10 minutes on CPU.")

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except ImportError:
        print("ERROR: transformers/peft not installed. Activate the venv first.")
        sys.exit(1)

    print("  Loading base model...")
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.float16, low_cpu_mem_usage=True)
    tokenizer = AutoTokenizer.from_pretrained(str(ADAPTER_DIR))

    print("  Loading LoRA adapter...")
    model = PeftModel.from_pretrained(base, str(ADAPTER_DIR))

    print("  Merging weights...")
    model = model.merge_and_unload()

    print(f"  Saving merged model to {MERGED_DIR} ...")
    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(MERGED_DIR))
    tokenizer.save_pretrained(str(MERGED_DIR))
    print("  Merge complete.")


def check_cmake():
    if shutil.which("cmake"):
        return
    print("cmake not found. Installing...")
    run("sudo apt-get install -y cmake build-essential")


def setup_llama_cpp():
    if not LLAMA_DIR.exists():
        print("Cloning llama.cpp (conversion tools only)...")
        run(f"git clone --depth=1 https://github.com/ggerganov/llama.cpp {quote(LLAMA_DIR)}")

    print("Building llama.cpp conversion tools...")
    build_dir = LLAMA_DIR / "build"
    build_dir.mkdir(exist_ok=True)
    run("cmake .. -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF", cwd=build_dir)
    run("cmake --build . --config Release --target llama-quantize -j4", cwd=build_dir)

    # Install Python conversion dependencies into the backend venv
    venv_pip = BASE_DIR / "backend" / "venv" / "bin" / "pip"
    run(f"{quote(venv_pip)} install -q gguf sentencepiece protobuf")


def convert_to_gguf():
    convert_script = LLAMA_DIR / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        # Try alternate name
        convert_script = LLAMA_DIR / "convert-hf-to-gguf.py"

    if not convert_script.exists():
        print(f"ERROR: conversion script not found in {LLAMA_DIR}")
        sys.exit(1)

    venv_python = BASE_DIR / "backend" / "venv" / "bin" / "python3"
    print(f"\nConverting merged model → GGUF ...")
    run(f"{quote(venv_python)} {quote(convert_script)} {quote(MERGED_DIR)} --outfile {quote(GGUF_OUTPUT)} --outtype f16")


def quantize_gguf():
    quantize_bin = (
        LLAMA_DIR / "build" / "bin" / "llama-quantize"
    )
    if not quantize_bin.exists():
        # Search for it
        candidates = list(LLAMA_DIR.rglob("llama-quantize"))
        if not candidates:
            print("WARNING: llama-quantize not found, skipping quantization.")
            return

        quantize_bin = candidates[0]

    q4_output = OUTPUT_DIR / "email-support-q4.gguf"
    print(f"\nQuantizing to Q4_K_M (smaller + faster on CPU)...")
    run(f"{quote(quantize_bin)} {quote(GGUF_OUTPUT)} {quote(q4_output)} Q4_K_M")
    print(f"Quantized model: {q4_output}")
    return q4_output


def create_modelfile(gguf_path: Path):
    modelfile = OUTPUT_DIR / "Modelfile"
    modelfile.write_text(f"""FROM {gguf_path}

SYSTEM \"\"\"You are a professional customer support agent.
Be professional, concise, and helpful. Sign off as: Support Team\"\"\"

PARAMETER temperature 0.3
PARAMETER num_ctx 2048
""")
    print(f"\nModelfile created: {modelfile}")
    return modelfile


def load_into_ollama(modelfile: Path):
    print(f"\nLoading model into Ollama as '{MODEL_NAME}'...")
    run(f"ollama create {MODEL_NAME} -f {quote(modelfile)}")
    print(f"\nModel loaded! Test it with:")
    print(f"  ollama run {MODEL_NAME}")
    print(f"\nThen update backend/.env:")
    print(f"  LLM_MODEL={MODEL_NAME}")


def main():
    print("=" * 60)
    print(" Converting fine-tuned model → GGUF → Ollama")
    print("=" * 60)

    if not ADAPTER_DIR.exists():
        print(f"ERROR: Trained adapter not found at {ADAPTER_DIR}")
        print("Run finetune_cpu.py or the Colab notebook first.")
        sys.exit(1)

    merge_lora_into_base()
    check_cmake()
    setup_llama_cpp()
    convert_to_gguf()
    q4_path = quantize_gguf()
    final_gguf = q4_path if q4_path and q4_path.exists() else GGUF_OUTPUT
    modelfile  = create_modelfile(final_gguf)
    load_into_ollama(modelfile)

    print("\n" + "=" * 60)
    print(" Done! Your fine-tuned model is ready in Ollama.")
    print("=" * 60)


if __name__ == "__main__":
    main()
