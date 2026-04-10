"""
News & Sentiment Specialist Agent.

Receives pre-fetched news headlines and macro context strings and returns
a structured NewsAgentOutput via a cheap LLM call.
"""
from __future__ import annotations

import logging

from ._base import NewsAgentOutput, call_cheap_llm, Provider

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a market intelligence analyst specialising in news sentiment and macro regime analysis. "
    "You receive recent news headlines and macro indicators for a financial asset and must "
    "classify the sentiment and identify key catalysts and risks. "
    "Focus ONLY on the provided headlines and data — do not invent news. "
    "CRITICAL: Respond with ONLY raw JSON matching the exact schema requested."
)


def _build_prompt(
    symbol: str,
    asset_type: str,
    news_context: str,
    macro_context: str,
) -> str:
    context_sections = []
    if news_context:
        context_sections.append(news_context)
    if macro_context:
        context_sections.append(macro_context)

    if not context_sections:
        context_block = "No news or macro data available."
    else:
        context_block = "\n\n".join(context_sections)

    return f"""News and macro context for {symbol} ({asset_type}):

{context_block}

Analyse the above and return EXACTLY this JSON (no markdown, no prose):
{{
  "overall_sentiment": "BULLISH|BEARISH|MIXED|NEUTRAL",
  "catalysts": ["<catalyst 1>", "<catalyst 2>", "<catalyst 3>"],
  "risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "news_score": <integer 0-100, 50=neutral, >65=bullish, <35=bearish>,
  "macro_regime": "<1-sentence macro regime summary: risk-on/risk-off, dominant forces>"
}}

Rules:
- overall_sentiment must be derived from the actual headlines provided, not assumed
- catalysts and risks must cite specific events or factors from the data
- news_score must reflect the balance of bullish vs bearish signals in the headlines
- If no news was provided, set news_score to 50 and overall_sentiment to NEUTRAL"""


async def run_news_agent(
    symbol: str,
    asset_type: str,
    news_context: str,
    macro_context: str,
    synthesis_provider: Provider,
) -> NewsAgentOutput:
    """
    Run the news & sentiment specialist agent.
    Returns NewsAgentOutput with defaults if LLM call fails or no context available.
    """
    if not news_context and not macro_context:
        logger.debug("No news/macro context for %s — returning defaults", symbol)
        return NewsAgentOutput()

    system = _SYSTEM
    user_msg = _build_prompt(symbol, asset_type, news_context, macro_context)

    try:
        result = await call_cheap_llm(system, user_msg, synthesis_provider, max_tokens=500)
        if result:
            return NewsAgentOutput(**result)
    except Exception as exc:
        logger.warning("News agent failed for %s: %s", symbol, exc)

    return NewsAgentOutput()
