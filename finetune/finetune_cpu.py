"""
Local CPU fine-tuning using transformers + peft (LoRA).

Base model : TinyLlama/TinyLlama-1.1B-Chat-v1.0  (1.1B params, no HF auth needed)
Method     : LoRA (rank 16) — trains only ~1% of params, feasible on CPU
Hardware   : i7-6820HQ, 23GB RAM — expected ~3-5 hours for 100 examples, 3 epochs

Output     : ./output/final_model  (HuggingFace format)
             ./output/model.gguf   (Ollama-ready, requires llama.cpp converter)

Usage:
    pip install -r requirements_finetune.txt
    python finetune_cpu.py
"""

import json
import os
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
TRAIN_DATA = BASE_DIR / "data" / "training" / "combined_train.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "finetuned"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_MODEL   = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
LORA_RANK    = 16
LORA_ALPHA   = 32
EPOCHS       = 3
BATCH_SIZE   = 2
GRAD_ACCUM   = 4          # effective batch = 8
LEARNING_RATE = 2e-4
MAX_LENGTH   = 1024
SAVE_STEPS   = 50


def load_dataset(path: Path):
    if not path.exists():
        print(f"ERROR: Training data not found at {path}")
        print("Run: python prepare_dataset.py first")
        sys.exit(1)

    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"Loaded {len(records)} training records from {path.name}")
    return records


def format_prompt(record: dict) -> str:
    return (
        f"<|system|>\nYou are a helpful customer support assistant.</s>\n"
        f"<|user|>\n{record['instruction']}\n\n{record['input']}</s>\n"
        f"<|assistant|>\n{record['output']}</s>"
    )


def main():
    print("=" * 60)
    print(" Local CPU Fine-tuning — LoRA")
    print(f" Model  : {BASE_MODEL}")
    print(f" Data   : {TRAIN_DATA}")
    print(f" Output : {OUTPUT_DIR}")
    print("=" * 60)

    # ── Imports (deferred so errors show cleanly) ──────────────────
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer
        from transformers import DataCollatorForLanguageModeling
        from peft import LoraConfig, get_peft_model, TaskType
        from datasets import Dataset
    except ImportError as e:
        print(f"\nMissing dependency: {e}")
        print("Run: pip install -r requirements_finetune.txt")
        sys.exit(1)

    print(f"\nPyTorch version : {torch.__version__}")
    print(f"Device          : CPU (no GPU detected)")

    # ── Load tokenizer + model ─────────────────────────────────────
    print(f"\nLoading model: {BASE_MODEL} ...")
    print("  (First run will download ~2GB — be patient)")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float32,   # float32 for CPU stability
        low_cpu_mem_usage=True,
    )
    print(f"  Parameters: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")

    # ── Apply LoRA ─────────────────────────────────────────────────
    lora_config = LoraConfig(
        task_type    = TaskType.CAUSAL_LM,
        r            = LORA_RANK,
        lora_alpha   = LORA_ALPHA,
        lora_dropout = 0.05,
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"],
        bias         = "none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Prepare dataset ────────────────────────────────────────────
    records  = load_dataset(TRAIN_DATA)
    texts    = [format_prompt(r) for r in records]

    def tokenize(examples):
        return tokenizer(
            examples["text"],
            truncation=True,
            max_length=MAX_LENGTH,
            padding="max_length",
        )

    hf_dataset = Dataset.from_dict({"text": texts})
    tokenized  = hf_dataset.map(tokenize, batched=True, remove_columns=["text"])
    tokenized  = tokenized.map(lambda x: {"labels": x["input_ids"].copy()})

    # ── Training ───────────────────────────────────────────────────
    training_args = TrainingArguments(
        output_dir                  = str(OUTPUT_DIR / "checkpoints"),
        num_train_epochs            = EPOCHS,
        per_device_train_batch_size = BATCH_SIZE,
        gradient_accumulation_steps = GRAD_ACCUM,
        learning_rate               = LEARNING_RATE,
        logging_steps               = 10,
        save_steps                  = SAVE_STEPS,
        save_total_limit            = 2,
        warmup_steps                = 5,
        weight_decay                = 0.01,
        fp16                        = False,   # CPU: no fp16
        bf16                        = False,
        use_cpu                     = True,
        dataloader_num_workers      = 0,
        report_to                   = "none",
        no_cuda                     = True,
    )

    trainer = Trainer(
        model         = model,
        args          = training_args,
        train_dataset = tokenized,
        data_collator = DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )

    print("\nStarting training...")
    print("Expected time: 3-5 hours on i7 CPU. Let it run — loss should decrease each epoch.\n")

    trainer.train()

    # ── Save final model ───────────────────────────────────────────
    final_path = OUTPUT_DIR / "final_model"
    model.save_pretrained(str(final_path))
    tokenizer.save_pretrained(str(final_path))
    print(f"\nModel saved to: {final_path}")

    # ── GGUF conversion instructions ──────────────────────────────
    print("\n" + "=" * 60)
    print(" Training Complete!")
    print("=" * 60)
    print("""
Next: Convert to GGUF and load into Ollama.

Run the conversion script:
    python convert_to_ollama.py

Then test:
    ollama run email-support
""")


if __name__ == "__main__":
    main()
