"""
Trading Analysis Service — Multi-provider AI engine.

Supports three providers:
  • claude   — Anthropic Claude (best reasoning, web search tool)
  • openai   — OpenAI GPT-4o
  • gemini   — Google Gemini 1.5 Flash (free tier)

Two analysis modes are distinguished by horizon:
  • trading  — short-to-medium term (days / weeks): momentum, technicals, catalysts
  • investing — medium-to-long term (months / years): fundamentals, DCF, moat
"""
from __future__ import annotations

import json
import logging
import re
from typing import Literal

import httpx

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

Provider = Literal["claude", "openai", "gemini"]
Horizon = Literal["trading", "investing"]

# ─── Shared prompt builders ───────────────────────────────────────────────────

def _build_system(horizon: Horizon) -> str:
    if horizon == "trading":
        return (
            "You are an elite quantitative trader at a top-tier prop-trading desk. "
            "Your specialty: short-to-medium term (days to weeks) momentum, technical analysis, "
            "options flow, and news-driven catalysts. "
            "You think in terms of risk/reward, entry/exit levels, stop-losses, and short-term price targets. "
            "Be specific with price levels and timeframes. "
            "CRITICAL: Respond with ONLY raw JSON — no markdown, no backticks, no prose."
        )
    return (
        "You are a senior portfolio manager at a $15B AUM long-only fund. "
        "Your specialty: medium-to-long term (months to years) fundamental analysis, "
        "DCF valuation, competitive moats, sector rotation, and macro positioning. "
        "You think in terms of intrinsic value, margin of safety, and business quality. "
        "Be specific with valuation multiples and earnings estimates. "
        "CRITICAL: Respond with ONLY raw JSON — no markdown, no backticks, no prose."
    )


def _build_user_message(
    symbol: str,
    name: str,
    price: float | None,
    asset_type: str,
    horizon: Horizon,
    extra: str = "",
) -> str:
    price_str = f"${price:,.4f}" if price else "unknown"
    horizon_label = "SHORT-TO-MEDIUM TERM TRADING (days to weeks)" if horizon == "trading" else "MEDIUM-TO-LONG TERM INVESTING (months to years)"

    return f"""Perform a {horizon_label} analysis for: {name} ({symbol})
Asset class: {asset_type}
Current price: {price_str}
{extra}

Return EXACTLY this JSON structure (raw JSON only):
{{
  "rec": "STRONG BUY|BUY|HOLD|SELL|STRONG SELL",
  "score": <integer 0-100>,
  "horizon": "<e.g. 2-4 weeks>" ,
  "confidence": "High|Medium|Low",
  "target": <number>,
  "targetLow": <number>,
  "targetHigh": <number>,
  "stopLoss": <number>,
  "entryZone": "<price range>",
  "summary": "<2-3 sentence executive summary with specific numbers>",
  "technical": "<momentum, trend, key levels, volume, RSI, MACD>",
  "fundamental": "<valuation, earnings, growth, competitive position>",
  "news": "<recent headlines and their market impact>",
  "support": [<level1>, <level2>],
  "resistance": [<level1>, <level2>],
  "catalysts": ["<catalyst 1>", "<catalyst 2>", "<catalyst 3>"],
  "risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "allocation": "<e.g. 3-5% of portfolio>",
  "strategyNote": "<how this fits the {horizon} strategy specifically>"
}}"""


def _extract_json(text: str) -> dict | None:
    """Extract the first valid JSON object from a string."""
    cleaned = re.sub(r"```json?|```", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


# ─── Claude ───────────────────────────────────────────────────────────────────

async def _run_claude(system: str, user_msg: str) -> dict | None:
    api_key = settings.anthropic_api_key.get_secret_value()
    if not api_key:
        raise ValueError("Anthropic API key not configured")

    # Use web_search tool so Claude can fetch live data
    payload = {
        "model": settings.claude_model,
        "max_tokens": 2000,
        "system": system,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": user_msg}],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    text = next(
        (b["text"] for b in data.get("content", []) if b.get("type") == "text"), ""
    )
    return _extract_json(text)


# ─── OpenAI ───────────────────────────────────────────────────────────────────

async def _run_openai(system: str, user_msg: str) -> dict | None:
    api_key = settings.openai_api_key.get_secret_value()
    if not api_key:
        raise ValueError("OpenAI API key not configured")

    payload = {
        "model": settings.openai_model,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    text = data["choices"][0]["message"]["content"]
    return _extract_json(text)


# ─── Gemini ───────────────────────────────────────────────────────────────────

async def _run_gemini(system: str, user_msg: str) -> dict | None:
    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        raise ValueError("Gemini API key not configured")

    model = settings.gemini_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user_msg}]}],
        "generationConfig": {
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, params={"key": api_key}, json=payload)
        resp.raise_for_status()
        data = resp.json()

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _extract_json(text)


# ─── Public entry point ───────────────────────────────────────────────────────

async def run_trading_analysis(
    symbol: str,
    name: str,
    price: float | None,
    asset_type: str,
    horizon: Horizon,
    provider: Provider,
    extra: str = "",
) -> dict:
    """
    Run AI trading/investing analysis for an asset.

    Returns the parsed JSON result dict.
    Raises ValueError if API key missing, RuntimeError if all attempts fail.
    """
    system = _build_system(horizon)
    user_msg = _build_user_message(symbol, name, price, asset_type, horizon, extra)

    logger.info("Running %s analysis via %s for %s", horizon, provider, symbol)

    try:
        if provider == "claude":
            result = await _run_claude(system, user_msg)
        elif provider == "openai":
            result = await _run_openai(system, user_msg)
        elif provider == "gemini":
            result = await _run_gemini(system, user_msg)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    except ValueError:
        raise
    except Exception as exc:
        logger.exception("Analysis failed for %s via %s: %s", symbol, provider, exc)
        raise RuntimeError(f"Analysis failed via {provider}: {exc}") from exc

    if result is None:
        raise RuntimeError(f"{provider} returned unparseable response for {symbol}")

    # Ensure strategyNote exists
    result.setdefault("strategyNote", f"Analysis performed with {horizon} horizon via {provider}.")
    result["_provider"] = provider
    result["_horizon"] = horizon
    return result
