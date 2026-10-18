"""
provider.py — Gemini-First AI Provider
========================================
Uses the modern google-genai SDK (google.genai).
Models are tried in order (GEMINI_MODELS) with fallback on overload.
Local Ollama support is kept in code but disabled by default.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path)
log = logging.getLogger(__name__)

# ── Runtime state ─────────────────────────────────────────────────────────────
_current_provider: str = os.getenv("AI_PROVIDER", "gemini").lower()
VALID_PROVIDERS = {"local", "gemini"}

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Lazy Gemini client (created once on first use) ────────────────────────────
_gemini_client = None

def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        if not _GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set in backend/.env\n"
                "Get your free key at: https://aistudio.google.com/app/apikey"
            )
        try:
            from google import genai
            _gemini_client = genai.Client(api_key=_GEMINI_API_KEY)
            log.info("Gemini client initialised (google-genai SDK).")
        except ImportError:
            raise RuntimeError(
                "google-genai is not installed. Run: pip install google-genai"
            )
    return _gemini_client


# ── Provider state ────────────────────────────────────────────────────────────

def get_provider() -> str:
    return _current_provider


def set_provider(provider: str) -> str:
    global _current_provider
    provider = provider.lower().strip()
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Invalid provider '{provider}'. Choose from: {VALID_PROVIDERS}")
    _current_provider = provider
    log.info("AI provider switched to: %s", _current_provider)
    return _current_provider


# Primary and fallback models — tried in order on 503 overload errors
# Override with GEMINI_MODELS="model-a,model-b" in .env
_GEMINI_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3.5-flash,gemini-flash-latest").split(",")
    if m.strip()
]


def get_model_label() -> str:
    """Human-readable name of the model currently answering emails (for the dashboard)."""
    if get_provider() == "local":
        return os.getenv("RAG_MODEL", "qwen2.5:7b")
    return _GEMINI_MODELS[0] if _GEMINI_MODELS else "gemini"


def _gemini_chat(prompt: str, temperature: float = 0.0, json_mode: bool = False) -> str:
    client = _get_gemini_client()
    from google.genai import types
    import time

    last_error = None
    for model in _GEMINI_MODELS:
        for attempt in range(2):                  # up to 2 attempts per model
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        top_p=0.95,
                        top_k=40,
                        max_output_tokens=2048,
                        response_mime_type="application/json" if json_mode else None,
                    ),
                )
                text = (response.text or "").strip()
                if not text:
                    # Safety block or token budget spent on thinking — treat as a model failure
                    raise RuntimeError(f"empty response from {model}")
                if model != _GEMINI_MODELS[0]:
                    log.info("Used fallback model: %s", model)
                return text

            except Exception as e:
                last_error = e
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str:
                    if attempt == 0:
                        log.warning("Gemini %s overloaded (attempt 1/2). Retrying in 1s…", model)
                        time.sleep(1)
                        continue
                    else:
                        log.warning("Gemini %s still overloaded after retry. Switching to next model…", model)
                        break   # fast fallback to next model
                else:
                    log.warning("Gemini model %s failed: %s. Trying next model…", model, err_str)
                    break      # non-recoverable error — try next model

    raise RuntimeError(
        f"All Gemini models unavailable after retries. Last error: {last_error}"
    )


# ── Ollama call (kept for future local mode) ──────────────────────────────────

def _ollama_chat(model: str, prompt: str, temperature: float = 0.0) -> str:
    try:
        import ollama
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature},
            keep_alive="60m",
        )
        return response["message"]["content"].strip()
    except Exception as e:
        raise RuntimeError(
            f"Ollama is not running or model '{model}' is not loaded. "
            f"Switch to Gemini or start Ollama. Error: {e}"
        )


# ── Public interface ──────────────────────────────────────────────────────────

def classify(prompt: str) -> str:
    """Classify email via Gemini or Ollama."""
    if get_provider() == "local":
        try:
            return _ollama_chat(os.getenv("LLM_MODEL", "email-support-v2"), prompt, 0.0)
        except Exception as e:
            log.warning("Local Ollama classify failed (%s). Falling back to Gemini...", e)
    log.debug("classify → Gemini")
    return _gemini_chat(prompt, temperature=0.0, json_mode=True)


def generate(prompt: str) -> str:
    """Generate reply via Gemini or Ollama."""
    if get_provider() == "local":
        try:
            return _ollama_chat(os.getenv("RAG_MODEL", "qwen2.5:7b"), prompt, 0.3)
        except Exception as e:
            log.warning("Local Ollama generate failed (%s). Falling back to Gemini...", e)
    log.debug("generate → Gemini")
    return _gemini_chat(prompt, temperature=0.5)
