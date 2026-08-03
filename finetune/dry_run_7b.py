import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import sys

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

def dry_run():
    print(f"--- Dry Run: Loading {BASE_MODEL} ---")
    try:
        tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
        print("Tokenizer loaded.")
        
        # Load only 1 layer to test memory and download
        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map="cpu"
        )
        print("Model weights loaded into RAM successfully.")
        print(f"Memory allocated: {torch.cuda.memory_allocated() if torch.cuda.is_available() else 'CPU Memory'}")
        
    except Exception as e:
        print(f"\nDRY RUN FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    dry_run()
