"""
Centralized Swappable LLM Client
================================
Supports Google Gemini (default) and any OpenAI-compatible provider (OpenAI, Groq,
Ollama, vLLM, DeepSeek) via environment variables or explicit parameters.

Configuration precedence:
  1. Function arguments (e.g. api_key, model, provider)
  2. Streamlit session state / UI inputs
  3. Environment variables:
     - LLM_PROVIDER ('gemini' or 'openai')
     - LLM_MODEL or GEMINI_MODEL
     - LLM_API_KEY or GEMINI_API_KEY or OPENAI_API_KEY
     - LLM_BASE_URL (for OpenAI-compatible endpoints)

Tracks input/output tokens and estimated cost across runs.
"""

import os
import re
import json
import time
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("LLMClient")

# ==============================================================================
# TOKEN & COST TRACKING (GLOBAL RUN METRICS)
# ==============================================================================
RUN_METRICS = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "estimated_cost_usd": 0.0,
    "model_used": None,
    "provider_used": None,
}

# Approximate cost per 1M tokens (USD)
MODEL_PRICING = {
    "gemini-3.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-3.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "default": {"input": 0.15, "output": 0.60},
}


def reset_run_stats():
    """Resets global token counters and cost trackers for a fresh run."""
    global RUN_METRICS
    RUN_METRICS = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "model_used": None,
        "provider_used": None,
    }


def get_run_stats() -> Dict[str, Any]:
    """Returns a copy of the current run statistics."""
    return dict(RUN_METRICS)


def record_usage(input_tokens: int, output_tokens: int, model: str, provider: str):
    """Updates global counters and computes estimated run cost."""
    global RUN_METRICS
    RUN_METRICS["calls"] += 1
    RUN_METRICS["input_tokens"] += input_tokens
    RUN_METRICS["output_tokens"] += output_tokens
    RUN_METRICS["total_tokens"] += (input_tokens + output_tokens)
    RUN_METRICS["model_used"] = model
    RUN_METRICS["provider_used"] = provider

    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
    cost = (input_tokens / 1_000_000.0) * pricing["input"] + (output_tokens / 1_000_000.0) * pricing["output"]
    RUN_METRICS["estimated_cost_usd"] += cost


def estimate_token_count(text: str) -> int:
    """Fallback tokenizer: roughly 4 characters per token."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def extract_json_from_response(raw_text: str) -> Any:
    """
    Safely extracts and parses JSON from LLM text output,
    handling markdown fences (```json ... ```) or bare text.
    """
    if not raw_text:
        return {}
    cleaned = raw_text.strip()
    # Strip markdown code blocks
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try finding the first '{' or '[' and last '}' or ']'
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Failed to parse valid JSON from LLM response: {raw_text[:200]}")


# ==============================================================================
# PROVIDER IMPLEMENTATIONS
# ==============================================================================
def _call_gemini_sdk(
    prompt: str,
    schema: Optional[Dict[str, Any]] = None,
    system_instruction: Optional[str] = None,
    model: str = "gemini-3.5-flash-lite",
    api_key: Optional[str] = None,
    temperature: float = 0.2,
) -> Tuple[Any, int, int]:
    """Invokes Google GenAI SDK with JSON schema enforcement."""
    from google import genai
    from google.genai import types

    active_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY")
    if not active_key:
        raise ValueError("Gemini API key not found. Provide api_key or set GEMINI_API_KEY.")

    client = genai.Client(api_key=active_key)
    config_params: Dict[str, Any] = {
        "response_mime_type": "application/json",
        "temperature": temperature,
    }
    if schema:
        config_params["response_schema"] = schema
    if system_instruction:
        config_params["system_instruction"] = system_instruction

    config = types.GenerateContentConfig(**config_params)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )

    raw_text = response.text or ""
    parsed = extract_json_from_response(raw_text)

    # Token extraction
    in_tokens = 0
    out_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        in_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        out_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    if in_tokens == 0:
        in_tokens = estimate_token_count(prompt)
        out_tokens = estimate_token_count(raw_text)

    return parsed, in_tokens, out_tokens


def _call_openai_compatible(
    prompt: str,
    schema: Optional[Dict[str, Any]] = None,
    system_instruction: Optional[str] = None,
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.2,
) -> Tuple[Any, int, int]:
    """Invokes any OpenAI-compatible HTTP endpoint via standard urllib."""
    active_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    target_base = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    url = f"{target_base.rstrip('/')}/chat/completions"

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {active_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        res_json = json.loads(resp.read().decode("utf-8"))

    raw_content = res_json["choices"][0]["message"]["content"]
    parsed = extract_json_from_response(raw_content)

    usage = res_json.get("usage", {})
    in_tokens = usage.get("prompt_tokens", estimate_token_count(prompt))
    out_tokens = usage.get("completion_tokens", estimate_token_count(raw_content))

    return parsed, in_tokens, out_tokens


# ==============================================================================
# UNIFIED PUBLIC API
# ==============================================================================
def generate_json(
    prompt: str,
    schema: Optional[Dict[str, Any]] = None,
    system_instruction: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.2,
    max_retries: int = 3,
) -> Any:
    """
    Unified entry point for LLM structured JSON generation.
    Swappable between Gemini and any OpenAI-compatible provider with exponential backoff.
    """
    active_provider = (
        provider
        or os.getenv("LLM_PROVIDER")
        or ("openai" if os.getenv("OPENAI_API_KEY") and not os.getenv("GEMINI_API_KEY") else "gemini")
    ).lower()

    if active_provider == "gemini":
        active_model = model or os.getenv("GEMINI_MODEL") or os.getenv("LLM_MODEL") or "gemini-3.5-flash-lite"
    else:
        active_model = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"

    last_error = None
    for attempt in range(max_retries):
        try:
            if active_provider == "gemini":
                result, in_tok, out_tok = _call_gemini_sdk(
                    prompt=prompt,
                    schema=schema,
                    system_instruction=system_instruction,
                    model=active_model,
                    api_key=api_key,
                    temperature=temperature,
                )
            else:
                result, in_tok, out_tok = _call_openai_compatible(
                    prompt=prompt,
                    schema=schema,
                    system_instruction=system_instruction,
                    model=active_model,
                    api_key=api_key,
                    base_url=base_url,
                    temperature=temperature,
                )

            record_usage(in_tok, out_tok, active_model, active_provider)
            return result

        except Exception as e:
            err_msg = str(e)
            last_error = e

            # Missing API key fails immediately without pointless retries
            if "API key not found" in err_msg or "API key is required" in err_msg:
                raise last_error

            # Handle rate limiting (429) or temporary server error (503)
            is_rate_limit = "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "rate limit" in err_msg.lower()
            is_server_error = "503" in err_msg or "UNAVAILABLE" in err_msg or "overloaded" in err_msg.lower()

            if (is_rate_limit or is_server_error) and attempt < max_retries - 1:
                sleep_sec = (2.0 ** attempt) * 2.0
                logger.warning(
                    "LLM call rate-limited/busy (%s). Retrying in %.1fs (attempt %d/%d)...",
                    err_msg[:80], sleep_sec, attempt + 1, max_retries
                )
                time.sleep(sleep_sec)
                continue
            else:
                logger.error("LLM call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt == max_retries - 1:
                    raise last_error

    raise last_error or RuntimeError("LLM call failed after retries.")
