"""
Trading Analysis Service — Multi-Agent AI engine (Phase 3).

Orchestrates a 4-agent pipeline:
  1. TechnicalAgent   — interprets pre-computed indicator context (cheap LLM)
  2. NewsAgent        — interprets news + macro context (cheap LLM)
  3. FundamentalAgent — assesses intrinsic quality from training knowledge (cheap LLM)
  4. SynthesisAgent   — combines all three into a final recommendation (user's best model)

Supported synthesis providers:
  • claude   — Anthropic Claude Opus (best reasoning, web search tool)
  • openai   — OpenAI GPT-4o
  • gemini   — Google Gemini 2.0 Flash

Two analysis horizons:
  • trading  — short-to-medium term (days / weeks)
  • investing — medium-to-long term (months / years)

Falls back to single-LLM mode if specialist agents all return defaults.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Literal

import httpx

from config import get_settings
from services.agents.technical_agent import run_technical_agent
from services.agents.news_agent import run_news_agent
from services.agents.fundamental_agent import run_fundamental_agent
from services.agents.synthesis_agent import run_synthesis_agent

logger = logging.getLogger(__name__)
settings = get_settings()

Provider = Literal["claude", "openai", "gemini", "ollama"]
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

    has_technical = "=== Technical Analysis" in extra
    has_news      = "=== Recent News" in extra
    has_macro     = "=== Macro" in extra
    has_context   = has_technical or has_news or has_macro

    if has_context:
        news_step   = "\n3. NEWS ALIGNMENT: Do the provided headlines confirm or contradict the chart signal? Weight HIGH-SIGNIFICANCE news events." if has_news else ""
        macro_step  = "\n4. MACRO REGIME: Is the macro environment (Fear & Greed, DXY, VIX, yields) a headwind or tailwind? Does it support the position?" if has_macro else ""
        level_step_n = "5" if (has_news and has_macro) else ("4" if (has_news or has_macro) else "4")
        rr_step_n    = "6" if (has_news and has_macro) else ("5" if (has_news or has_macro) else "5")
        entry_step_n = "7" if (has_news and has_macro) else ("6" if (has_news or has_macro) else "6")

        reasoning_steps = f"""
REASONING STEPS — work through these before outputting JSON:
1. TREND CONFLUENCE: What do EMA9/21/50 say together? Is the trend aligned across timeframes?
2. MOMENTUM STATE: Are RSI, Stochastic, and MACD aligned? Any divergence between price and momentum?{news_step}{macro_step}
{level_step_n}. KEY LEVELS: Where are the nearest high-probability support and resistance levels? Use computed pivots and swing levels.
{rr_step_n}. RISK/REWARD: What is the risk/reward at current price for the stated horizon? ATR defines the stop width.
{entry_step_n}. ENTRY ZONE: Given ATR and the nearest support/resistance, what is the optimal entry zone?

After this internal reasoning, output ONLY the JSON below (no other text)."""
    else:
        reasoning_steps = "\nAfter your analysis, output ONLY the JSON below (no other text)."

    news_field = (
        '"news": "<summarize the PROVIDED news headlines above and their SPECIFIC market impact — cite actual sources>",'
        if has_news else
        '"news": "<recent relevant headlines and their market impact>",'
    )
    news_sentiment_field = (
        '\n  "newsSentiment": "BULLISH|BEARISH|MIXED|NEUTRAL",'
        if has_news else ""
    )
    macro_field = (
        '"macroContext": "<summarize macro regime impact: Fear & Greed, DXY trend, VIX level and what they mean for this trade>",'
        if has_macro else
        '"macroContext": "<macro environment summary>",'
    )

    return f"""Perform a {horizon_label} analysis for: {name} ({symbol})
Asset class: {asset_type}
Current price: {price_str}
{extra}
{reasoning_steps}

Return EXACTLY this JSON structure (raw JSON only, no markdown):
{{
  "rec": "STRONG BUY|BUY|HOLD|SELL|STRONG SELL",
  "score": <integer 0-100>,
  "horizon": "<e.g. 2-4 weeks>",
  "confidence": "High|Medium|Low",
  "target": <number>,
  "targetLow": <number>,
  "targetHigh": <number>,
  "stopLoss": <number>,
  "entryZone": "<price range derived from ATR and key levels>",
  "summary": "<2-3 sentence executive summary with specific price levels and key signals>",
  "technical": "<cite actual indicator values: RSI, MACD histogram, BB position, EMA alignment, volume ratio, patterns detected>",
  "fundamental": "<valuation, earnings/tokenomics, growth, competitive position>",
  {news_field}{news_sentiment_field}
  {macro_field}
  "support": [<level1>, <level2>],
  "resistance": [<level1>, <level2>],
  "catalysts": ["<catalyst 1>", "<catalyst 2>", "<catalyst 3>"],
  "risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "allocation": "<e.g. 3-5% of portfolio>",
  "strategyNote": "<how this fits the {horizon} strategy — reference specific signals from technicals, news, and macro>"
}}
IMPORTANT: All price targets and stop-loss MUST be derived from the computed support/resistance and ATR data. Do NOT invent price levels."""


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

def _anthropic_friendly_error(resp: httpx.Response) -> str:
    """Extract a human-readable error message from an Anthropic API error response."""
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message", "")
        if "credit balance is too low" in msg:
            return "Anthropic API credits depleted — please top up at console.anthropic.com/settings/billing"
        if msg:
            return f"Anthropic API error: {msg}"
    except Exception:
        pass
    return f"Anthropic API returned {resp.status_code}"


def _gemini_friendly_error(resp: httpx.Response) -> str:
    """Extract a human-readable error message from a Gemini API error response."""
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message", "")
        if resp.status_code == 429:
            return "Gemini free-tier quota exceeded — please wait a minute or enable billing at ai.google.dev"
        if resp.status_code == 503:
            return "Gemini is temporarily unavailable (503) — please retry in a moment"
        if msg:
            return f"Gemini API error: {msg[:200]}"
    except Exception:
        pass
    return f"Gemini API returned {resp.status_code}"


async def _run_claude(system: str, user_msg: str) -> dict | None:
    api_key = settings.anthropic_api_key.get_secret_value()
    if not api_key:
        raise ValueError("Anthropic API key not configured")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "web-search-2025-03-05",
        "content-type": "application/json",
    }

    payload = {
        "model": settings.claude_model,
        "max_tokens": 4000,
        "system": system,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        "messages": [{"role": "user", "content": user_msg}],
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
        )
        if resp.status_code == 400:
            # Check if it's a credits error (don't retry — it won't help)
            try:
                err_msg = resp.json().get("error", {}).get("message", "")
                if "credit" in err_msg.lower():
                    raise ValueError(_anthropic_friendly_error(resp))
            except ValueError:
                raise
            except Exception:
                pass
            # web_search beta not available — fall back to plain call
            logger.warning("web_search beta unavailable, retrying without tool")
            payload.pop("tools")
            headers.pop("anthropic-beta")
            payload["max_tokens"] = 2000
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            )
        if not resp.is_success:
            raise RuntimeError(_anthropic_friendly_error(resp))
        data = resp.json()

    # Extract final text — works for both plain responses and web-search responses
    # (web-search responses embed tool_use + tool_result blocks before the text block)
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
        if not resp.is_success:
            raise RuntimeError(_gemini_friendly_error(resp))
        data = resp.json()

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _extract_json(text)


# ─── Public entry point ───────────────────────────────────────────────────────

def _split_extra(extra: str) -> tuple[str, str, str]:
    """
    Extract tech / news / macro sections from the combined context string.
    Each section starts at its header and runs to the next header (or end).
    """
    tech_start  = extra.find("=== Technical Analysis")
    news_start  = extra.find("=== Recent News")
    macro_start = extra.find("=== Macro")

    def _slice(start: int, *next_starts: int) -> str:
        if start == -1:
            return ""
        end = min((s for s in next_starts if s > start), default=len(extra))
        return extra[start:end].strip()

    tech_ctx  = _slice(tech_start,  news_start, macro_start)
    news_ctx  = _slice(news_start,  macro_start)
    macro_ctx = _slice(macro_start)
    return tech_ctx, news_ctx, macro_ctx


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
    Run AI trading/investing analysis for an asset via the multi-agent pipeline.

    Pipeline:
      1. Three specialist agents run in parallel (cheap LLMs)
      2. Synthesis agent combines their outputs (user's best-model provider)

    Returns the parsed JSON result dict.
    Raises ValueError if synthesis API key missing, RuntimeError if all attempts fail.
    """
    logger.info("Running multi-agent %s analysis via %s for %s", horizon, provider, symbol)

    # Split pre-fetched context into per-agent inputs
    tech_ctx, news_ctx, macro_ctx = _split_extra(extra)

    horizon_label = "SHORT-TERM TRADING (days to weeks)" if horizon == "trading" else "MEDIUM-TO-LONG TERM INVESTING (months to years)"

    # ── Phase 1: Run 3 specialist agents in parallel ──────────────────────────
    tech_task = run_technical_agent(symbol, price, asset_type, tech_ctx, provider)
    news_task = run_news_agent(symbol, asset_type, news_ctx, macro_ctx, provider)
    fund_task = run_fundamental_agent(symbol, name, price, asset_type, horizon_label, provider)

    tech_out, news_out, fund_out = await asyncio.gather(
        tech_task, news_task, fund_task, return_exceptions=True
    )

    # Gracefully degrade: replace any failed agent with its default output
    from services.agents._base import TechAgentOutput, NewsAgentOutput, FundAgentOutput
    if isinstance(tech_out, Exception):
        logger.warning("TechAgent failed for %s: %s", symbol, tech_out)
        tech_out = TechAgentOutput()
    if isinstance(news_out, Exception):
        logger.warning("NewsAgent failed for %s: %s", symbol, news_out)
        news_out = NewsAgentOutput()
    if isinstance(fund_out, Exception):
        logger.warning("FundAgent failed for %s: %s", symbol, fund_out)
        fund_out = FundAgentOutput()

    logger.info(
        "Specialist agents complete for %s — tech:%d news:%d fund:%d",
        symbol, tech_out.tech_score, news_out.news_score, fund_out.fund_score,
    )

    # ── Phase 2: Synthesis agent ──────────────────────────────────────────────
    try:
        result = await run_synthesis_agent(
            symbol=symbol,
            name=name,
            price=price,
            asset_type=asset_type,
            horizon=horizon_label,
            provider=provider,
            tech=tech_out,
            news=news_out,
            fund=fund_out,
        )
    except ValueError:
        raise  # API key not configured — surface to caller
    except Exception as exc:
        logger.exception("Synthesis agent failed for %s: %s", symbol, exc)
        raise RuntimeError(f"Analysis synthesis failed via {provider}: {exc}") from exc

    return result
