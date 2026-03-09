"""
Centralised Ollama LLM client for the Admin-AI project.

Usage
-----
from aa.llm_client import call_llm, call_llm_chat, LLMError, MAIN_MODEL, LIGHT_MODEL

# Simple generate (no system prompt)
text = call_llm("Summarise AI in education in one sentence.")

# Generate with system prompt combined into a single prompt
text = call_llm(user_prompt, system_prompt="You are ...", model=LIGHT_MODEL)

# Chat endpoint (better instruction-following for complex tasks)
text = call_llm_chat(user_message, system_prompt="You are ...", model=MAIN_MODEL)
"""

import os
import requests

# ── Endpoint ──────────────────────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# ── Model aliases ─────────────────────────────────────────────────────────────
MAIN_MODEL  = os.environ.get("OLLAMA_MAIN_MODEL",  "llama3.1:8b")   # heavy – best reasoning
LIGHT_MODEL = os.environ.get("OLLAMA_LIGHT_MODEL", "llama3.2:3b")   # fast  – lighter tasks


class LLMError(Exception):
    """Raised when the Ollama API call fails."""


# ── /api/generate ─────────────────────────────────────────────────────────────

def call_llm(
    prompt: str,
    system_prompt: str = "",
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 300,
    timeout: int = 120,
) -> str:
    """
    Call Ollama /api/generate and return the response text.

    Parameters
    ----------
    prompt        : the user request / question
    system_prompt : optional instruction block prepended to the prompt
    model         : Ollama model name; defaults to MAIN_MODEL
    temperature   : sampling temperature (0 = deterministic)
    max_tokens    : maximum tokens the model may generate
    timeout       : HTTP timeout in seconds
    """
    model_name = model or MAIN_MODEL

    full_prompt = f"{system_prompt}\n\nUser request:\n{prompt}" if system_prompt else prompt

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":   model_name,
                "prompt":  full_prompt,
                "stream":  False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as exc:
        raise LLMError(f"call_llm failed ({model_name}): {exc}") from exc


# ── /api/chat ─────────────────────────────────────────────────────────────────

def call_llm_chat(
    user_message: str,
    system_prompt: str = "",
    model: str = "",
    temperature: float = 0.6,
    max_tokens: int = 600,
    timeout: int = 120,
) -> str:
    """
    Call Ollama /api/chat (supports system + user roles) and return the content.

    Preferred for instruction-heavy tasks where the model needs to follow a
    detailed system prompt (e.g. circular drafting).

    Parameters
    ----------
    user_message  : the user turn message
    system_prompt : system role instruction
    model         : Ollama model name; defaults to MAIN_MODEL
    temperature   : sampling temperature
    max_tokens    : maximum tokens the model may generate
    timeout       : HTTP timeout in seconds
    """
    model_name = model or MAIN_MODEL

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message})

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":    model_name,
                "messages": messages,
                "stream":   False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as exc:
        raise LLMError(f"call_llm_chat failed ({model_name}): {exc}") from exc
