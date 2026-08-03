#!/bin/bash

# Helper script to load the 7B model from Colab into Ollama

PROJECT_DIR="/home/parthiv/web/Email Automation"
DOWNLOADS_DIR="$HOME/Downloads"
MODEL_DEST="$PROJECT_DIR/data/finetuned/email-support-7b.gguf"
MODEL_NAME="email-support-7b"

echo "Looking for downloaded GGUF file in $DOWNLOADS_DIR..."

# Find the most recent GGUF file that looks like it came from our Colab
LATEST_GGUF=$(ls -t $DOWNLOADS_DIR/*Q4_K_M*.gguf 2>/dev/null | head -1)

if [ -z "$LATEST_GGUF" ]; then
    # Fallback search if the filename is different
    LATEST_GGUF=$(ls -t $DOWNLOADS_DIR/*.gguf 2>/dev/null | head -1)
fi

if [ -n "$LATEST_GGUF" ]; then
    echo "Found: $LATEST_GGUF"
    echo "Moving to $MODEL_DEST..."
    mv "$LATEST_GGUF" "$MODEL_DEST"
    
    echo "Creating Ollama model '$MODEL_NAME'..."
    ollama create $MODEL_NAME -f "$PROJECT_DIR/data/finetuned/Modelfile-7b"
    
    echo "Done! You can now test it with:"
    echo "ollama run $MODEL_NAME"
else
    echo "Error: No GGUF file found in $DOWNLOADS_DIR."
    echo "Please make sure the download from Colab has finished."
fi
