"""
Synthesis Agent — orchestrates 3 specialist outputs into a final recommendation.

Receives structured outputs from TechAgent, NewsAgent, and FundAgent and calls
the user's preferred best-model provider to produce the final unified analysis JSON.
"""
from __future__ import annotations

import json
import logging

from ._base import (
    TechAgentOutput,
    NewsAgentOutput,
    FundAgentOutput,
    call_synthesis_llm,
    Provider,
)

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are the Chief Investment Officer at a multi-strategy hedge fund. "
    "Three specialist analysts have provided their independent assessments below. "
    "Your job is to synthesise their findings into a single, actionable investment recommendation. "
    "Weight the signals according to the analysis horizon: "
    "  • SHORT-TERM trading: technicals 50% · news 35% · fundamentals 15% "
    "  • LONG-TERM investing: fundamentals 50% · technicals 25% · news 25% "
    "Be specific with price levels and cite the specialist findings in your reasoning. "
    "CRITICAL: Respond with ONLY raw JSON matching the exact schema requested."
)


def _build_prompt(
    symbol: str,
    name: str,
    price: float | None,
    asset_type: str,
    horizon: str,
    tech: TechAgentOutput,
    news: NewsAgentOutput,
    fund: FundAgentOutput,
) -> str:
    price_str = f"${price:,.4f}" if price else "unknown"
    is_trading = "trading" in horizon.lower() or "short" in horizon.lower() or "week" in horizon.lower()
    horizon_label = "SHORT-TERM TRADING (days to weeks)" if is_trading else "MEDIUM-TO-LONG TERM INVESTING (months to years)"
    weight_note = (
        "Weight: technicals 50% · news/sentiment 35% · fundamentals 15%"
        if is_trading else
        "Weight: fundamentals 50% · technicals 25% · news/sentiment 25%"
    )

    tech_block = json.dumps(tech.model_dump(), indent=2)
    news_block = json.dumps(news.model_dump(), indent=2)
    fund_block = json.dumps(fund.model_dump(), indent=2)

    return f"""Asset: {name} ({symbol}) | Class: {asset_type} | Price: {price_str}
Horizon: {horizon_label}
{weight_note}

=== TECHNICAL ANALYST OUTPUT (tech_score: {tech.tech_score}/100) ===
{tech_block}

=== NEWS & SENTIMENT ANALYST OUTPUT (news_score: {news.news_score}/100) ===
{news_block}

=== FUNDAMENTAL ANALYST OUTPUT (fund_score: {fund.fund_score}/100) ===
{fund_block}

Synthesise the above and return EXACTLY this JSON (no markdown, no prose):
{{
  "rec": "STRONG BUY|BUY|HOLD|SELL|STRONG SELL",
  "score": <integer 0-100, weighted composite of the three specialist scores>,
  "horizon": "<specific timeframe, e.g. '2-4 weeks' or '6-12 months'>",
  "confidence": "High|Medium|Low",
  "target": <number — price target derived from technicals and fundamentals>,
  "targetLow": <number — conservative target>,
  "targetHigh": <number — optimistic target>,
  "stopLoss": <number — must match technical stop_zone or be derived from ATR>,
  "entryZone": "<price range from technical entry_zone>",
  "summary": "<2-3 sentence executive summary citing specific signals from all three analysts>",
  "technical": "<cite actual values from tech analyst: trend, RSI, MACD, patterns, entry_zone>",
  "fundamental": "<cite fund analyst: fair_value_estimate, valuation_label, growth_outlook>",
  "news": "<cite news analyst: overall_sentiment, top catalysts, macro_regime>",
  "newsSentiment": "<from NewsAgent: BULLISH|BEARISH|MIXED|NEUTRAL>",
  "macroContext": "<from NewsAgent: macro_regime string>",
  "support": [<tech support_levels>],
  "resistance": [<tech resistance_levels>],
  "catalysts": [<merged catalyst list from news and fund agents, max 4>],
  "risks": [<merged risk list from news and fund agents, max 4>],
  "allocation": "<recommended position size, e.g. '3-5% of portfolio'>",
  "strategyNote": "<how the weighted signals combine for this horizon — reference specific analyst findings>"
}}

IMPORTANT:
- rec must reflect the weighted composite: if tech=75, news=40, fund=55 (trading weights) → composite ≈ 58
- stopLoss MUST be the tech_agent stop_zone (if provided) — do not invent a different level
- entryZone MUST match tech_agent entry_zone (if provided)
- If any specialist returned defaults (score=50, trend=UNKNOWN), weight that analyst at 0 and note it"""


async def run_synthesis_agent(
    symbol: str,
    name: str,
    price: float | None,
    asset_type: str,
    horizon: str,
    provider: Provider,
    tech: TechAgentOutput,
    news: NewsAgentOutput,
    fund: FundAgentOutput,
) -> dict:
    """
    Run the synthesis agent to produce the final recommendation.

    Returns a dict with the full analysis JSON.
    Raises ValueError if API key not configured.
    Raises RuntimeError if the LLM call fails or returns unparseable output.
    """
    system = _SYSTEM
    user_msg = _build_prompt(symbol, name, price, asset_type, horizon, tech, news, fund)

    logger.info("Running synthesis agent via %s for %s (horizon=%s)", provider, symbol, horizon)

    result = await call_synthesis_llm(system, user_msg, provider, max_tokens=4000)

    if result is None:
        raise RuntimeError(f"Synthesis agent ({provider}) returned unparseable response for {symbol}")

    # Annotate provenance
    result["_provider"] = provider
    result["_horizon"] = horizon
    result["_agent_scores"] = {
        "tech": tech.tech_score,
        "news": news.news_score,
        "fund": fund.fund_score,
    }
    result.setdefault(
        "strategyNote",
        f"Multi-agent analysis via {provider} — tech:{tech.tech_score} news:{news.news_score} fund:{fund.fund_score}",
    )

    return result
