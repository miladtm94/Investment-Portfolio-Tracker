"""
Fundamental Analysis Specialist Agent.

Uses a cheap LLM with its training-data knowledge to assess the fundamental
quality of an asset — valuation, moat, growth outlook, and key risks.
No live data injection (unlike technical/news agents); the LLM's parametric
knowledge is the source here.
"""
from __future__ import annotations

import logging

from ._base import FundAgentOutput, call_cheap_llm, Provider

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a fundamental equity and crypto analyst with deep knowledge of valuation, "
    "business quality, tokenomics, and competitive dynamics. "
    "You assess intrinsic value, growth prospects, competitive moat, and key risks "
    "using your knowledge of the asset. Be concise and specific. "
    "CRITICAL: Respond with ONLY raw JSON matching the exact schema requested."
)


def _build_prompt(
    symbol: str,
    name: str,
    price: float | None,
    asset_type: str,
    horizon: str,
) -> str:
    price_str = f"${price:,.4f}" if price else "unknown"
    is_crypto = "CRYPTO" in asset_type.upper()

    if is_crypto:
        valuation_guidance = (
            "For crypto: assess market cap vs. total addressable market, "
            "tokenomics (supply schedule, inflation rate, burn mechanisms), "
            "network activity trends, and developer ecosystem health."
        )
    else:
        valuation_guidance = (
            "For equities: assess P/E vs. sector peers, EV/EBITDA, revenue growth rate, "
            "operating margin trajectory, competitive moat (brand/network/switching costs/cost), "
            "and balance sheet strength."
        )

    return f"""Perform a fundamental analysis for: {name} ({symbol})
Asset class: {asset_type}
Current price: {price_str}
Analysis horizon: {horizon}

{valuation_guidance}

Return EXACTLY this JSON (no markdown, no prose):
{{
  "fair_value_estimate": "<price or range, e.g. '$185-$210' or 'N/A for speculative assets'>",
  "valuation_label": "UNDERVALUED|FAIR_VALUE|OVERVALUED|SPECULATIVE",
  "growth_outlook": "<1-2 sentence growth trajectory assessment with specific metrics where known>",
  "competitive_position": "<moat assessment: brand/network/switching costs/cost advantages or tokenomic defensibility>",
  "key_risks": ["<fundamental risk 1>", "<fundamental risk 2>", "<fundamental risk 3>"],
  "fund_score": <integer 0-100, 50=neutral/average, >65=above average quality, <35=below average>
}}

Rules:
- fair_value_estimate must be a specific price or range, not vague language
- valuation_label must be SPECULATIVE for assets where DCF is inapplicable (meme coins, early-stage crypto)
- fund_score reflects business/protocol quality and value relative to price — not momentum
- Acknowledge uncertainty where appropriate; do not confabulate specific earnings figures"""


async def run_fundamental_agent(
    symbol: str,
    name: str,
    price: float | None,
    asset_type: str,
    horizon: str,
    synthesis_provider: Provider,
) -> FundAgentOutput:
    """
    Run the fundamental analyst specialist agent.
    Returns FundAgentOutput with defaults if the LLM call fails.
    """
    system = _SYSTEM
    user_msg = _build_prompt(symbol, name, price, asset_type, horizon)

    try:
        result = await call_cheap_llm(system, user_msg, synthesis_provider, max_tokens=600)
        if result:
            return FundAgentOutput(**result)
    except Exception as exc:
        logger.warning("Fundamental agent failed for %s: %s", symbol, exc)

    return FundAgentOutput()
