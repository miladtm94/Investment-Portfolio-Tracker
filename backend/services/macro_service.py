"""
Macro Context Service — Phase 2 of AI Analysis Enhancement Plan.

Fetches macro regime data for injection into AI analysis prompts:
  • Fear & Greed Index  — alternative.me (free)
  • BTC Dominance       — CoinGecko /global (free)
  • DXY (USD Index)     — Yahoo Finance DX-Y.NYB
  • VIX (Equity Vol)    — Yahoo Finance ^VIX
  • 10Y Treasury Yield  — Yahoo Finance ^TNX

All fetches run in parallel. Results cached in Redis for 15 minutes.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from shared.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

_CACHE_KEY = "trading:macro:context"
_CACHE_TTL = 900  # 15 minutes


# ─── Individual fetchers ──────────────────────────────────────────────────────

async def _fetch_fear_greed() -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=1")
            resp.raise_for_status()
            item = resp.json()["data"][0]
            return {"value": int(item["value"]), "label": item["value_classification"]}
    except Exception as exc:
        logger.warning("Fear & Greed fetch failed: %s", exc)
        return None


async def _fetch_btc_dominance() -> Optional[float]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get("https://api.coingecko.com/api/v3/global")
            if resp.status_code == 429:
                return None
            resp.raise_for_status()
            pct = resp.json()["data"]["market_cap_percentage"]
            return round(pct.get("btc", 0), 1)
    except Exception as exc:
        logger.warning("BTC dominance fetch failed: %s", exc)
        return None


async def _fetch_yahoo_metric(url_path: str) -> Optional[dict]:
    """
    Fetch latest price and 5-day % change from Yahoo Finance.
    url_path must be the pre-encoded path segment, e.g. '%5EVIX' for ^VIX.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{url_path}"
    try:
        async with httpx.AsyncClient(
            timeout=8.0, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            resp = await client.get(url, params={"range": "5d", "interval": "1d"})
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
    except Exception as exc:
        logger.warning("Yahoo metric fetch failed for %s: %s", url_path, exc)
        return None

    meta = result.get("meta", {})
    closes = [
        c for c in result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if c is not None
    ]
    price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    if price is None:
        return None

    change_5d = None
    if len(closes) >= 2 and closes[0]:
        change_5d = round((price / closes[0] - 1) * 100, 2)

    return {"price": round(price, 2), "change_5d": change_5d}


# ─── Interpreters ─────────────────────────────────────────────────────────────

def _interpret_fear_greed(value: int, label: str) -> str:
    if value <= 25:
        return f"{label} — contrarian bullish signal (extreme fear often precedes reversals)"
    elif value <= 45:
        return f"{label} — cautious market sentiment"
    elif value <= 55:
        return f"{label}"
    elif value <= 75:
        return f"{label} — positive momentum, watch for overextension"
    else:
        return f"{label} — extreme greed, heightened correction risk"


def _interpret_vix(price: float) -> str:
    if price < 15:
        return "very low — complacent market, potential for volatility spike"
    elif price < 20:
        return "low — calm conditions, risk-on environment"
    elif price < 25:
        return "moderate — balanced risk"
    elif price < 35:
        return "elevated — risk-off conditions, defensive positioning"
    else:
        return "extreme — flight to safety, avoid leveraged positions"


def _interpret_tnx(price: float) -> str:
    if price < 3.5:
        return "low — accommodative for risk assets and growth"
    elif price < 4.2:
        return "moderate — balanced environment"
    elif price < 5.0:
        return "elevated — risk premium pressure, headwind for growth"
    else:
        return "very high — significant valuation headwind, especially for long-duration assets"


def _interpret_dxy(price: float, change: Optional[float]) -> str:
    level = f"{price:.1f}"
    if change is None:
        return level
    trend_note = ""
    if change > 0.5:
        trend_note = " — USD strengthening (bearish for crypto/commodities)"
    elif change < -0.5:
        trend_note = " — USD weakening (bullish for crypto/commodities/EM)"
    else:
        trend_note = " — USD stable"
    return f"{level} ({change:+.1f}% this week){trend_note}"


def _macro_regime_summary(
    fear_greed: Optional[dict],
    dxy: Optional[dict],
    vix: Optional[dict],
    asset_class: str,
) -> str:
    """Generate a one-line macro regime interpretation."""
    is_crypto = asset_class.upper() == "CRYPTO"
    parts = []

    if fear_greed:
        fg = fear_greed["value"]
        if fg < 30:
            parts.append("FEAR-driven market")
        elif fg > 70:
            parts.append("GREED-driven market")

    if vix and isinstance(vix, dict):
        v = vix["price"]
        if v > 30:
            parts.append("high equity vol (risk-off)")
        elif v < 15:
            parts.append("low vol (risk-on bias)")

    if dxy and isinstance(dxy, dict) and dxy.get("change_5d") is not None:
        chg = dxy["change_5d"]
        if is_crypto:
            if chg > 0.5:
                parts.append("strengthening USD (crypto headwind)")
            elif chg < -0.5:
                parts.append("weakening USD (crypto tailwind)")

    if parts:
        return "  → Macro regime: " + " + ".join(parts)
    return "  → Macro regime: NEUTRAL / TRANSITIONAL"


# ─── Public interface ─────────────────────────────────────────────────────────

async def fetch_macro_context(asset_class: str) -> str:
    """
    Fetch macro regime context and return a formatted prompt string.
    Cached in Redis for 15 minutes.
    """
    cached = await cache_get(_CACHE_KEY)
    if cached is not None:
        return cached

    # All fetches in parallel
    results = await asyncio.gather(
        _fetch_fear_greed(),
        _fetch_btc_dominance(),
        _fetch_yahoo_metric("DX-Y.NYB"),
        _fetch_yahoo_metric("%5EVIX"),
        _fetch_yahoo_metric("%5ETNX"),
        return_exceptions=True,
    )

    def _safe(v):
        return v if not isinstance(v, Exception) else None

    fear_greed = _safe(results[0])
    btc_dom    = _safe(results[1])
    dxy        = _safe(results[2])
    vix        = _safe(results[3])
    tnx        = _safe(results[4])

    lines = ["\n=== Macro & Market Regime Context ==="]

    if fear_greed:
        interp = _interpret_fear_greed(fear_greed["value"], fear_greed["label"])
        lines.append(f"  Fear & Greed Index : {fear_greed['value']}/100 — {interp}")

    if btc_dom is not None:
        dom_note = (
            "rising — risk-off, Bitcoin dominance, altcoins underperforming"
            if btc_dom > 55
            else "falling — risk-on, altcoin season conditions"
        )
        lines.append(f"  BTC Dominance      : {btc_dom}% — {dom_note}")

    if dxy and isinstance(dxy, dict):
        lines.append(f"  DXY (USD Index)    : {_interpret_dxy(dxy['price'], dxy.get('change_5d'))}")

    if vix and isinstance(vix, dict):
        lines.append(f"  VIX (Equity Vol)   : {vix['price']} — {_interpret_vix(vix['price'])}")

    if tnx and isinstance(tnx, dict):
        lines.append(f"  10Y Treasury Yield : {tnx['price']}% — {_interpret_tnx(tnx['price'])}")

    # Regime summary
    lines.append(_macro_regime_summary(fear_greed, dxy, vix, asset_class))

    # Only return if we got at least 2 data points
    if len(lines) < 3:
        return ""

    result = "\n".join(lines)
    await cache_set(_CACHE_KEY, result, ttl=_CACHE_TTL)
    return result
