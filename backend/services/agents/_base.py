"""
Shared LLM call infrastructure for the multi-agent pipeline.

Provides:
  • Pydantic output models for each specialist agent
  • Parameterised low-level LLM runners (Gemini, OpenAI, Claude, Ollama) with model override
  • call_cheap_llm()     — auto-selects cheapest available provider
  • call_synthesis_llm() — uses user-chosen provider with best model
"""
from __future__ import annotations

import json
import logging
import re
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

Provider = Literal["claude", "openai", "gemini", "ollama", "lmstudio"]


# ─── Pydantic output models ───────────────────────────────────────────────────

class TechAgentOutput(BaseModel):
    """Output of the Technical Analysis specialist agent."""
    model_config = ConfigDict(extra="allow")
    trend: str = "UNKNOWN"
    momentum_signal: str = ""
    support_levels: list[float] = []
    resistance_levels: list[float] = []
    patterns: str = "None detected"
    entry_zone: str = ""
    stop_zone: float | None = None
    tech_score: int = 50


class NewsAgentOutput(BaseModel):
    """Output of the News & Sentiment specialist agent."""
    model_config = ConfigDict(extra="allow")
    overall_sentiment: str = "NEUTRAL"   # BULLISH | BEARISH | MIXED | NEUTRAL
    catalysts: list[str] = []
    risks: list[str] = []
    news_score: int = 50                 # 0-100, 50=neutral
    macro_regime: str = ""


class FundAgentOutput(BaseModel):
    """Output of the Fundamental Analysis specialist agent."""
    model_config = ConfigDict(extra="allow")
    fair_value_estimate: str = "N/A"
    valuation_label: str = "UNKNOWN"     # UNDERVALUED | FAIR_VALUE | OVERVALUED | SPECULATIVE
    growth_outlook: str = ""
    competitive_position: str = ""
    key_risks: list[str] = []
    fund_score: int = 50                 # 0-100


# ─── JSON extraction ──────────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    """Extract the first valid JSON object from LLM text output."""
    cleaned = re.sub(r"```json?|```", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


# ─── Error formatters ─────────────────────────────────────────────────────────

def _anthropic_error(resp: httpx.Response) -> str:
    try:
        msg = resp.json().get("error", {}).get("message", "")
        if "credit balance is too low" in msg:
            return "Anthropic API credits depleted — please top up at console.anthropic.com/settings/billing"
        if msg:
            return f"Anthropic API error: {msg[:300]}"
    except Exception:
        pass
    return f"Anthropic API returned {resp.status_code}"


def _gemini_error(resp: httpx.Response) -> str:
    try:
        msg = resp.json().get("error", {}).get("message", "")
        if resp.status_code == 429:
            return "Gemini free-tier quota exceeded — please wait or enable billing at ai.google.dev"
        if resp.status_code == 503:
            return "Gemini temporarily unavailable — please retry"
        if msg:
            return f"Gemini API error: {msg[:200]}"
    except Exception:
        pass
    return f"Gemini API returned {resp.status_code}"


# ─── Parameterised LLM runners ────────────────────────────────────────────────

async def _run_gemini_model(
    system: str,
    user_msg: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> dict | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    base_payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user_msg}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Try with JSON mode first (not all Gemma models support responseMimeType)
        payload = {**base_payload, "generationConfig": {**base_payload["generationConfig"], "responseMimeType": "application/json"}}
        resp = await client.post(url, params={"key": api_key}, json=payload)
        if resp.status_code == 400:
            err = resp.json().get("error", {}).get("message", "")
            if "responseMimeType" in err or "not supported" in err.lower():
                logger.debug("JSON mode unsupported for %s — retrying without responseMimeType", model)
                resp = await client.post(url, params={"key": api_key}, json=base_payload)
        if not resp.is_success:
            raise RuntimeError(_gemini_error(resp))
        data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        return None
    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    return extract_json(text)


async def _run_openai_model(
    system: str,
    user_msg: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> dict | None:
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return extract_json(data["choices"][0]["message"]["content"])


async def _run_claude_model(
    system: str,
    user_msg: str,
    model: str,
    api_key: str,
    max_tokens: int,
    use_web_search: bool = False,
) -> dict | None:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }
    if use_web_search:
        headers["anthropic-beta"] = "web-search-2025-03-05"
        payload["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages", headers=headers, json=payload
        )
        if resp.status_code == 400:
            try:
                err_msg = resp.json().get("error", {}).get("message", "")
                if "credit" in err_msg.lower():
                    raise ValueError(_anthropic_error(resp))
            except ValueError:
                raise
            except Exception:
                pass
            # Web search beta unavailable — retry without it
            if use_web_search:
                logger.warning("Web search beta unavailable, retrying without tool")
                headers.pop("anthropic-beta", None)
                payload.pop("tools", None)
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages", headers=headers, json=payload
                )
        if not resp.is_success:
            raise RuntimeError(_anthropic_error(resp))
        data = resp.json()

    text = next(
        (b["text"] for b in data.get("content", []) if b.get("type") == "text"), ""
    )
    return extract_json(text)


# ─── Ollama (local) runner ────────────────────────────────────────────────────

async def _resolve_ollama_model(host: str, preferred: str, fallback: str) -> str:
    """Return the first available model from Ollama's model list."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{host}/api/tags")
            if resp.is_success:
                names = {m["name"] for m in resp.json().get("models", [])}
                if preferred in names:
                    return preferred
                if fallback in names:
                    logger.info("Ollama model %r not found, using fallback %r", preferred, fallback)
                    return fallback
                if names:
                    chosen = next(iter(names))
                    logger.info("Ollama preferred/fallback not found, using %r", chosen)
                    return chosen
    except Exception as exc:
        logger.debug("Ollama model resolution failed: %s", exc)
    return preferred  # Best guess — let the call fail naturally


async def _run_ollama_model(
    system: str,
    user_msg: str,
    model: str,
    host: str,
    max_tokens: int,
) -> dict | None:
    """
    Call a locally running Ollama model via its OpenAI-compatible chat endpoint.
    Runs fully on-device — no data leaves the machine.
    """
    payload = {
        "model": model,
        "stream": False,
        "options": {"num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(f"{host}/api/chat", json=payload)
        except httpx.ConnectError:
            raise RuntimeError("Ollama is not running — start it with: ollama serve")
        if not resp.is_success:
            raise RuntimeError(f"Ollama returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()

    text = data.get("message", {}).get("content", "")
    return extract_json(text)


# ─── LM Studio (local OpenAI-compatible server) ──────────────────────────────

async def _resolve_lmstudio_model(host: str, preferred: str) -> str:
    """Return the first model loaded in LM Studio, or preferred if specified."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{host}/v1/models")
            if resp.is_success:
                models = resp.json().get("data", [])
                if models:
                    ids = [m["id"] for m in models]
                    if preferred and preferred in ids:
                        return preferred
                    return ids[0]
    except Exception as exc:
        logger.debug("LM Studio model resolution failed: %s", exc)
    return preferred or "local-model"


async def _run_lmstudio_model(
    system: str,
    user_msg: str,
    model: str,
    host: str,
    max_tokens: int,
) -> dict | None:
    """
    Call a locally running LM Studio model via its OpenAI-compatible API.
    No API key required. Runs fully on-device.
    """
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(f"{host}/v1/chat/completions", json=payload)
        except httpx.ConnectError:
            raise RuntimeError("LM Studio server not running — enable it in LM Studio → Local Server tab")
        if not resp.is_success:
            raise RuntimeError(f"LM Studio returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()

    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return extract_json(text)


async def _run_lmstudio_chat(
    messages: list[dict],
    system: str,
    host: str,
    model: str,
    max_tokens: int,
) -> str:
    """Multi-turn chat via LM Studio OpenAI-compatible endpoint."""
    msgs = [{"role": "system", "content": system}] + messages
    payload = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(f"{host}/v1/chat/completions", json=payload)
        except httpx.ConnectError:
            raise RuntimeError("LM Studio server not running — enable it in LM Studio → Local Server tab")
        if not resp.is_success:
            raise RuntimeError(f"LM Studio returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


# ─── Multi-turn chat callers (for advisor & conversational use) ───────────────

async def _run_openai_chat(
    messages: list[dict],
    system: str,
    model: str,
    api_key: str,
    max_tokens: int,
    base_url: str = "https://api.openai.com/v1",
) -> str:
    """Multi-turn chat via OpenAI-compatible endpoint."""
    msgs = [{"role": "system", "content": system}] + messages
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "messages": msgs},
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def _run_gemini_chat(
    messages: list[dict],
    system: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> str:
    """Multi-turn chat via Gemini generateContent API."""
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(url, params={"key": api_key}, json=payload)
        if not resp.is_success:
            raise RuntimeError(_gemini_error(resp))
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _run_claude_chat(
    messages: list[dict],
    system: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> str:
    """Multi-turn chat via Anthropic Messages API (httpx, no SDK)."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": model, "max_tokens": max_tokens, "system": system, "messages": messages},
        )
        if not resp.is_success:
            raise RuntimeError(_anthropic_error(resp))
    text = next(
        (b["text"] for b in resp.json().get("content", []) if b.get("type") == "text"), ""
    )
    return text


async def _run_ollama_chat(
    messages: list[dict],
    system: str,
    model: str,
    host: str,
    max_tokens: int,
) -> str:
    """Multi-turn chat via Ollama /api/chat endpoint."""
    payload = {
        "model": model,
        "stream": False,
        "options": {"num_predict": max_tokens},
        "messages": [{"role": "system", "content": system}] + messages,
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(f"{host}/api/chat", json=payload)
        except httpx.ConnectError:
            raise RuntimeError("Ollama is not running — start it with: ollama serve")
        if not resp.is_success:
            raise RuntimeError(f"Ollama returned {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("message", {}).get("content", "")


async def call_chat_llm(
    messages: list[dict],
    system: str,
    provider: Provider,
    max_tokens: int = 2000,
) -> str:
    """
    Multi-turn chat call using any supported provider.

    messages: [{"role": "user"|"assistant", "content": str}, ...]
    Returns the assistant's text response as a string.
    """
    if provider == "gemini":
        api_key = settings.gemini_api_key.get_secret_value()
        if not _key_valid(api_key):
            raise ValueError("Gemini API key not configured")
        return await _run_gemini_chat(messages, system, settings.gemini_model, api_key, max_tokens)

    elif provider == "openai":
        api_key = settings.openai_api_key.get_secret_value()
        if not _key_valid(api_key):
            raise ValueError("OpenAI API key not configured")
        return await _run_openai_chat(messages, system, settings.openai_model, api_key, max_tokens)

    elif provider == "claude":
        api_key = settings.anthropic_api_key.get_secret_value()
        if not _key_valid(api_key):
            raise ValueError("Anthropic API key not configured")
        return await _run_claude_chat(messages, system, settings.claude_model, api_key, max_tokens)

    elif provider == "ollama":
        model = await _resolve_ollama_model(
            settings.ollama_host, settings.ollama_model, settings.ollama_model_fallback
        )
        return await _run_ollama_chat(messages, system, model, settings.ollama_host, max_tokens)

    elif provider == "lmstudio":
        model = await _resolve_lmstudio_model(settings.lmstudio_host, settings.lmstudio_model)
        return await _run_lmstudio_chat(messages, system, settings.lmstudio_host, model, max_tokens)

    else:
        raise ValueError(f"Unknown provider: {provider}")


# ─── Unified callers ──────────────────────────────────────────────────────────

def _key_valid(key: str) -> bool:
    return bool(key) and len(key) > 10 and not key.startswith("your-") and key != "sk-..."


async def call_cheap_llm(
    system: str,
    user_msg: str,
    synthesis_provider: Provider,
    max_tokens: int = 800,
) -> dict | None:
    """
    Call the cheapest available LLM for specialist agent work.

    Priority order:
      1. Ollama (local)    — if synthesis provider is 'ollama'
      2. Gemini/Gemma API  — free tier, preferred for structured extraction
      3. GPT-4o-mini       — if OpenAI key available
      4. Synthesis provider fallback (user's chosen model, reduced tokens)

    Returns None if all attempts fail — callers should use their default output.
    """
    # 1. Local models — always first when selected (free, private, on-device)
    if synthesis_provider == "lmstudio":
        try:
            model = await _resolve_lmstudio_model(settings.lmstudio_host, settings.lmstudio_model)
            result = await _run_lmstudio_model(system, user_msg, model, settings.lmstudio_host, max_tokens)
            if result is not None:
                return result
        except Exception as exc:
            logger.debug("Cheap LM Studio call failed: %s", exc)

    if synthesis_provider == "ollama":
        try:
            model = await _resolve_ollama_model(
                settings.ollama_host, settings.ollama_model_cheap, settings.ollama_model_fallback
            )
            result = await _run_ollama_model(system, user_msg, model, settings.ollama_host, max_tokens)
            if result is not None:
                return result
        except Exception as exc:
            logger.debug("Cheap Ollama call failed: %s", exc)

    # 2. Gemini/Gemma (Google API)
    gemini_key = settings.gemini_api_key.get_secret_value()
    if _key_valid(gemini_key):
        try:
            result = await _run_gemini_model(
                system, user_msg, settings.agent_model_cheap, gemini_key, max_tokens
            )
            if result is not None:
                return result
        except Exception as exc:
            logger.debug("Cheap Gemini call failed: %s", exc)

    # 3. GPT-4o-mini
    openai_key = settings.openai_api_key.get_secret_value()
    if _key_valid(openai_key):
        try:
            result = await _run_openai_model(
                system, user_msg, "gpt-4o-mini", openai_key, max_tokens
            )
            if result is not None:
                return result
        except Exception as exc:
            logger.debug("Cheap GPT-4o-mini call failed: %s", exc)

    # 4. Fallback to synthesis provider
    try:
        if synthesis_provider == "gemini" and _key_valid(gemini_key):
            return await _run_gemini_model(
                system, user_msg, settings.gemini_model, gemini_key, max_tokens
            )
        elif synthesis_provider == "openai" and _key_valid(openai_key):
            return await _run_openai_model(
                system, user_msg, settings.openai_model, openai_key, max_tokens
            )
        elif synthesis_provider == "claude":
            claude_key = settings.anthropic_api_key.get_secret_value()
            if _key_valid(claude_key):
                return await _run_claude_model(
                    system, user_msg, settings.agent_model_synthesis, claude_key, max_tokens
                )
    except ValueError:
        raise  # Credits error — propagate
    except Exception as exc:
        logger.debug("Cheap fallback call failed: %s", exc)

    return None


async def call_synthesis_llm(
    system: str,
    user_msg: str,
    provider: Provider,
    max_tokens: int = 4000,
) -> dict | None:
    """
    Call the synthesis (best) LLM using the user-selected provider.
    Claude synthesis includes web search capability.
    Ollama runs fully locally — no data leaves the machine.
    """
    if provider == "lmstudio":
        model = await _resolve_lmstudio_model(settings.lmstudio_host, settings.lmstudio_model)
        logger.info("Synthesis via local LM Studio model: %s", model)
        return await _run_lmstudio_model(system, user_msg, model, settings.lmstudio_host, max_tokens)
    elif provider == "ollama":
        model = await _resolve_ollama_model(
            settings.ollama_host, settings.ollama_model, settings.ollama_model_fallback
        )
        logger.info("Synthesis via local Ollama model: %s", model)
        return await _run_ollama_model(system, user_msg, model, settings.ollama_host, max_tokens)
    elif provider == "claude":
        api_key = settings.anthropic_api_key.get_secret_value()
        if not _key_valid(api_key):
            raise ValueError("Anthropic API key not configured")
        return await _run_claude_model(
            system, user_msg, settings.agent_model_synthesis, api_key, max_tokens,
            use_web_search=True,
        )
    elif provider == "openai":
        api_key = settings.openai_api_key.get_secret_value()
        if not _key_valid(api_key):
            raise ValueError("OpenAI API key not configured")
        return await _run_openai_model(
            system, user_msg, settings.openai_model, api_key, max_tokens
        )
    elif provider == "gemini":
        api_key = settings.gemini_api_key.get_secret_value()
        if not _key_valid(api_key):
            raise ValueError("Gemini API key not configured")
        return await _run_gemini_model(
            system, user_msg, settings.gemini_model, api_key, max_tokens
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ─── Ollama availability check (for frontend status) ─────────────────────────

async def get_ollama_status() -> dict:
    """Check Ollama availability and return available models."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            if resp.is_success:
                models = [m["name"] for m in resp.json().get("models", [])]
                return {"available": True, "models": models, "host": settings.ollama_host}
    except Exception:
        pass
    return {"available": False, "models": [], "host": settings.ollama_host}


async def get_lmstudio_status() -> dict:
    """Check LM Studio server availability and return loaded models."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.lmstudio_host}/v1/models")
            if resp.is_success:
                data = resp.json().get("data", [])
                models = [m["id"] for m in data]
                return {
                    "available": True,
                    "models": models,
                    "active_model": models[0] if models else None,
                    "host": settings.lmstudio_host,
                }
    except Exception:
        pass
    return {"available": False, "models": [], "active_model": None, "host": settings.lmstudio_host}
