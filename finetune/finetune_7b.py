"""
7B Model CPU Fine-tuning (LoRA).
Optimized for 23GB RAM.
"""

import json
import os
import sys
import torch
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
TRAIN_DATA = BASE_DIR / "data" / "training" / "7b_kb_train.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "finetuned-7b"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Config (Optimized for CPU & 23GB RAM) ──────────────────────────────────────
BASE_MODEL    = "Qwen/Qwen2.5-7B-Instruct"
LORA_RANK     = 8           # Lower rank saves memory
LORA_ALPHA    = 16
EPOCHS        = 5           # More epochs for small dataset
BATCH_SIZE    = 1           # Strict minimum for RAM
GRAD_ACCUM    = 4
LEARNING_RATE = 1e-4
MAX_LENGTH    = 1024

def load_dataset(path: Path):
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

def format_prompt(record: dict) -> str:
    # Use Qwen 2.5 ChatML Template
    return (
        f"<|im_start|>system\n"
        f"{record['instruction']}<|im_end|>\n"
        f"<|im_start|>user\n"
        f"{record['input']}<|im_end|>\n"
        f"<|im_start|>assistant\n"
        f"{record['output']}<|im_end|>"
    )

def main():
    print("=" * 60)
    print(" 7B Model CPU Fine-tuning — ArtCloud Knowledge Injection")
    print(f" Model  : {BASE_MODEL}")
    print(f" RAM    : 23GB available")
    print("=" * 60)

    try:
        from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer
        from peft import LoraConfig, get_peft_model, TaskType
        from datasets import Dataset
    except ImportError:
        print("Missing dependencies. Run: pip install transformers peft datasets accelerate adafactor")
        sys.exit(1)

    # 1. Load Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token = tokenizer.eos_token

    # 2. Load Model in bfloat16 to save 50% RAM
    print(f"Loading {BASE_MODEL} in bfloat16...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        device_map="cpu"
    )
    
    # Enable gradient checkpointing to save memory during backprop
    model.gradient_checkpointing_enable()

    # 3. Apply LoRA
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        target_modules=["q_proj", "v_proj"], # Minimum layers to save RAM
        lora_dropout=0.05,
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 4. Prepare Data
    records = load_dataset(TRAIN_DATA)
    texts = [format_prompt(r) for r in records]
    
    hf_dataset = Dataset.from_dict({"text": texts})
    tokenized = hf_dataset.map(
        lambda x: tokenizer(x["text"], truncation=True, max_length=MAX_LENGTH, padding="max_length"),
        batched=True,
        remove_columns=["text"]
    )
    tokenized = tokenized.map(lambda x: {"labels": x["input_ids"].copy()})

    # 5. Training Arguments (Using Adafactor for low memory)
    training_args = TrainingArguments(
        output_dir=str(OUTPUT_DIR / "checkpoints"),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        optim="adafactor",          # 50% less RAM than AdamW
        logging_steps=1,
        save_total_limit=1,
        fp16=False,
        bf16=False,                 # Transformers CPU Trainer often prefers float32 for stable updates
        use_cpu=True,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
    )

    print("\nStarting training (Expect 8+ hours)...")
    trainer.train()

    # 6. Save
    final_path = OUTPUT_DIR / "final_weights"
    model.save_pretrained(str(final_path))
    tokenizer.save_pretrained(str(final_path))
    print(f"\nDone! Weights saved to {final_path}")

if __name__ == "__main__":
    main()
