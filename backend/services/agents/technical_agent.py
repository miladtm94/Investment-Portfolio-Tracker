"""
Technical Analysis Specialist Agent.

Receives pre-computed technical indicator context (from TechnicalAnalysisEngine)
and returns a structured TechAgentOutput via a cheap LLM call.
"""
from __future__ import annotations

import logging

from ._base import TechAgentOutput, call_cheap_llm, Provider

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a professional technical analyst. "
    "You receive pre-computed technical indicator data for a financial asset and must "
    "interpret it to produce a structured trading signal. "
    "Focus ONLY on the chart data provided — do not speculate about fundamentals or news. "
    "CRITICAL: Respond with ONLY raw JSON matching the exact schema requested."
)


def _build_prompt(
    symbol: str,
    price: float | None,
    asset_type: str,
    tech_context: str,
) -> str:
    price_str = f"${price:,.4f}" if price else "unknown"
    return f"""Technical indicator data for {symbol} ({asset_type}) — current price {price_str}:

{tech_context}

Analyse the above indicator data and return EXACTLY this JSON (no markdown, no prose):
{{
  "trend": "BULLISH|BEARISH|NEUTRAL|MIXED",
  "momentum_signal": "<1-sentence momentum summary citing RSI, MACD, Stochastic values>",
  "support_levels": [<level1>, <level2>],
  "resistance_levels": [<level1>, <level2>],
  "patterns": "<detected candlestick/chart patterns or 'None detected'>",
  "entry_zone": "<optimal entry price range based on ATR and nearest support>",
  "stop_zone": <stop-loss price as float>,
  "tech_score": <integer 0-100, 50=neutral, >70=bullish signal, <30=bearish signal>
}}

Rules:
- tech_score must reflect confluence of EMA alignment, RSI, MACD, and volume signals
- stop_zone must be derived from ATR or nearest support — not invented
- entry_zone must reference specific computed price levels from the data"""


async def run_technical_agent(
    symbol: str,
    price: float | None,
    asset_type: str,
    tech_context: str,
    synthesis_provider: Provider,
) -> TechAgentOutput:
    """
    Run the technical analyst specialist agent.
    Returns TechAgentOutput with defaults if the LLM call fails.
    """
    if not tech_context:
        logger.debug("No technical context for %s — returning defaults", symbol)
        return TechAgentOutput()

    system = _SYSTEM
    user_msg = _build_prompt(symbol, price, asset_type, tech_context)

    try:
        result = await call_cheap_llm(system, user_msg, synthesis_provider, max_tokens=600)
        if result:
            return TechAgentOutput(**result)
    except Exception as exc:
        logger.warning("Technical agent failed for %s: %s", symbol, exc)

    return TechAgentOutput()
