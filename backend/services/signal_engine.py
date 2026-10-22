"""
Deterministic technical signal engine.

This is intentionally separate from the LLM-backed AI analysis pipeline. It
turns OHLCV candles into a transparent trade signal using indicator confluence,
ATR-based risk, support/resistance, and detected chart/candlestick patterns.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal

import numpy as np
import pandas as pd

from services.chart_patterns import ChartPatternDetector
from services.technical_engine import TechnicalAnalysisEngine

Signal = Literal["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]


@dataclass
class SignalEvidence:
    label: str
    verdict: str
    score: int
    explanation: str


class SignalEngine:
    """Rule-based signal analysis for one symbol/timeframe."""

    def __init__(self, ohlcv: list[dict], timeframe: str):
        self.timeframe = timeframe
        self.raw = ohlcv
        self.df = pd.DataFrame(ohlcv)
        if self.df.empty:
            return
        self.df = self.df.sort_values("date").reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")
        self.df.dropna(subset=["close"], inplace=True)
        for col in ("open", "high", "low"):
            if col not in self.df.columns:
                self.df[col] = self.df["close"]
        if "volume" not in self.df.columns:
            self.df["volume"] = 0
        self.df.reset_index(drop=True, inplace=True)

    def analyze(self) -> dict:
        if self.df.empty or len(self.df) < 30:
            raise ValueError("At least 30 candles are required for signal analysis")

        df = self.df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"].fillna(0)

        df["ema9"] = close.ewm(span=9, adjust=False).mean()
        df["ema21"] = close.ewm(span=21, adjust=False).mean()
        df["ema50"] = close.ewm(span=50, adjust=False).mean()
        df["rsi"] = _rsi(close)
        macd, macd_signal, macd_hist = _macd(close)
        df["macd"] = macd
        df["macd_signal"] = macd_signal
        df["macd_hist"] = macd_hist
        df["atr"] = _atr(high, low, close)
        bb_mid, bb_upper, bb_lower = _bollinger(close)
        df["bb_mid"] = bb_mid
        df["bb_upper"] = bb_upper
        df["bb_lower"] = bb_lower
        stoch_k, stoch_d = _stochastic(high, low, close)
        df["stoch_k"] = stoch_k
        df["stoch_d"] = stoch_d
        df["obv"] = (np.sign(close.diff()).fillna(0) * volume).cumsum()

        latest = df.iloc[-1]
        previous = df.iloc[-2]
        price = float(latest["close"])
        atr = _finite_float(latest["atr"], price * 0.02)
        atr = max(atr, price * 0.002)

        evidence: list[SignalEvidence] = []
        raw_score = 0

        trend_score, trend_text = self._score_trend(latest, previous)
        raw_score += trend_score
        evidence.append(SignalEvidence("Trend", _verdict(trend_score), trend_score, trend_text))

        momentum_score, momentum_text = self._score_momentum(latest, previous)
        raw_score += momentum_score
        evidence.append(SignalEvidence("Momentum", _verdict(momentum_score), momentum_score, momentum_text))

        volatility_score, volatility_text = self._score_volatility(latest, price)
        raw_score += volatility_score
        evidence.append(SignalEvidence("Volatility", _verdict(volatility_score), volatility_score, volatility_text))

        volume_score, volume_text = self._score_volume(df, latest)
        raw_score += volume_score
        evidence.append(SignalEvidence("Volume", _verdict(volume_score), volume_score, volume_text))

        pattern_score, pattern_text, candlestick_patterns, chart_patterns = self._score_patterns()
        raw_score += pattern_score
        evidence.append(SignalEvidence("Patterns", _verdict(pattern_score), pattern_score, pattern_text))

        signal = _signal_from_score(raw_score)
        score = round(max(0, min(95, 50 + raw_score / 2)))
        confidence = _confidence(raw_score, len(df), evidence)

        support, resistance = _support_resistance(df, price)
        plan = _build_trade_plan(signal, price, atr, support, resistance, latest)

        indicators = {
            "ema9": _round(latest["ema9"]),
            "ema21": _round(latest["ema21"]),
            "ema50": _round(latest["ema50"]),
            "rsi14": _round(latest["rsi"], 1),
            "macd": _round(latest["macd"], 4),
            "macdSignal": _round(latest["macd_signal"], 4),
            "macdHistogram": _round(latest["macd_hist"], 4),
            "atr14": _round(atr),
            "bollingerUpper": _round(latest["bb_upper"]),
            "bollingerMid": _round(latest["bb_mid"]),
            "bollingerLower": _round(latest["bb_lower"]),
            "stochasticK": _round(latest["stoch_k"], 1),
            "stochasticD": _round(latest["stoch_d"], 1),
            "volumeRatio": _round(_volume_ratio(df), 2),
        }

        return {
            "signal": signal,
            "score": score,
            "rawScore": round(raw_score),
            "confidence": confidence,
            "timeframe": self.timeframe,
            "scoreMeaning": "Technical confluence score, not probability of profit.",
            "currentPrice": _round(price),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "candleCount": len(df),
            "lastCandleTime": str(df.iloc[-1].get("date", "")),
            "analysisWindow": {
                "from": str(df.iloc[0].get("date", "")),
                "to": str(df.iloc[-1].get("date", "")),
                "timeframe": self.timeframe,
            },
            "tradePlan": plan,
            "indicators": indicators,
            "levels": {
                "support": [_round(v) for v in support[:4]],
                "resistance": [_round(v) for v in resistance[:4]],
            },
            "evidence": [asdict(item) for item in evidence],
            "patterns": {
                "candlestick": candlestick_patterns,
                "chart": chart_patterns,
            },
            "explanation": _build_explanation(signal, confidence, evidence, plan),
            "warnings": _warnings(signal, confidence, len(df), atr, price),
        }

    def _score_trend(self, latest: pd.Series, previous: pd.Series) -> tuple[int, str]:
        price = latest["close"]
        ema9 = latest["ema9"]
        ema21 = latest["ema21"]
        ema50 = latest["ema50"]
        ema21_prev = previous["ema21"]

        if price > ema9 > ema21 > ema50:
            return 24, f"Price is above EMA9/21/50 and the moving averages are stacked bullishly."
        if price < ema9 < ema21 < ema50:
            return -24, f"Price is below EMA9/21/50 and the moving averages are stacked bearishly."

        score = 0
        details = []
        if price > ema21:
            score += 8
            details.append("price above EMA21")
        else:
            score -= 8
            details.append("price below EMA21")
        if ema9 > ema21:
            score += 7
            details.append("EMA9 above EMA21")
        else:
            score -= 7
            details.append("EMA9 below EMA21")
        if ema21 > ema21_prev:
            score += 5
            details.append("EMA21 rising")
        else:
            score -= 5
            details.append("EMA21 falling")
        return score, ", ".join(details) + "."

    def _score_momentum(self, latest: pd.Series, previous: pd.Series) -> tuple[int, str]:
        score = 0
        parts = []
        rsi = _finite_float(latest["rsi"], 50)
        if 52 <= rsi <= 68:
            score += 12
            parts.append(f"RSI {rsi:.1f} shows constructive momentum")
        elif 45 <= rsi < 52:
            score += 3
            parts.append(f"RSI {rsi:.1f} is neutral")
        elif 32 <= rsi < 45:
            score -= 10
            parts.append(f"RSI {rsi:.1f} shows weak momentum")
        elif rsi >= 72:
            score -= 8
            parts.append(f"RSI {rsi:.1f} is overbought")
        elif rsi <= 28:
            score += 6
            parts.append(f"RSI {rsi:.1f} is oversold and may bounce")

        hist = _finite_float(latest["macd_hist"], 0)
        hist_prev = _finite_float(previous["macd_hist"], 0)
        if latest["macd"] > latest["macd_signal"] and hist > 0:
            score += 12
            parts.append("MACD is above signal")
            if hist > hist_prev:
                score += 4
                parts.append("histogram is expanding")
        elif latest["macd"] < latest["macd_signal"] and hist < 0:
            score -= 12
            parts.append("MACD is below signal")
            if hist < hist_prev:
                score -= 4
                parts.append("histogram is weakening")

        if latest["stoch_k"] > latest["stoch_d"] and latest["stoch_k"] < 80:
            score += 5
            parts.append("stochastic is crossing up")
        elif latest["stoch_k"] < latest["stoch_d"] and latest["stoch_k"] > 20:
            score -= 5
            parts.append("stochastic is crossing down")

        return score, "; ".join(parts) + "."

    def _score_volatility(self, latest: pd.Series, price: float) -> tuple[int, str]:
        upper = latest["bb_upper"]
        lower = latest["bb_lower"]
        mid = latest["bb_mid"]
        if not np.isfinite(upper) or not np.isfinite(lower) or upper == lower:
            return 0, "Bollinger Bands are not available yet."
        bb_pos = (price - lower) / (upper - lower) * 100
        width = (upper - lower) / mid if mid else 0
        if price > upper:
            return 8, f"Price closed above the upper Bollinger Band; breakout pressure is present."
        if price < lower:
            return -8, f"Price closed below the lower Bollinger Band; downside pressure is present."
        if bb_pos < 15:
            return 6, f"Price is near the lower Bollinger Band ({bb_pos:.0f}%), where rebounds often start."
        if bb_pos > 85:
            return -6, f"Price is near the upper Bollinger Band ({bb_pos:.0f}%), so upside may be stretched."
        if width < 0.04:
            return 2, "Bollinger Bands are compressed, so a breakout setup may be forming."
        return 0, f"Price sits around the middle of the Bollinger range ({bb_pos:.0f}%)."

    def _score_volume(self, df: pd.DataFrame, latest: pd.Series) -> tuple[int, str]:
        ratio = _volume_ratio(df)
        if ratio is None:
            return 0, "Volume data is unavailable."
        obv_now = latest["obv"]
        obv_prev = df["obv"].iloc[-10] if len(df) >= 10 else df["obv"].iloc[0]
        price_change = latest["close"] - df["close"].iloc[-5] if len(df) >= 5 else 0
        if ratio >= 1.25 and obv_now > obv_prev and price_change > 0:
            return 9, f"Volume is {ratio:.2f}x average with rising OBV, confirming demand."
        if ratio >= 1.25 and obv_now < obv_prev and price_change < 0:
            return -9, f"Volume is {ratio:.2f}x average with falling OBV, confirming supply."
        if obv_now > obv_prev:
            return 3, "OBV is rising, suggesting mild accumulation."
        if obv_now < obv_prev:
            return -3, "OBV is falling, suggesting mild distribution."
        return 0, f"Volume is {ratio:.2f}x average with no strong OBV confirmation."

    def _score_patterns(self) -> tuple[int, str, list[dict], list[dict]]:
        score = 0
        candlestick: list[dict] = []
        chart: list[dict] = []

        tech = TechnicalAnalysisEngine(self.raw)
        for pat in getattr(tech, "_ctx").patterns:
            item = {
                "name": pat.name,
                "direction": pat.direction,
                "significance": pat.significance,
                "candlesAgo": pat.candles_ago,
            }
            candlestick.append(item)
            weight = 8 if pat.significance == "HIGH" else 4 if pat.significance == "MEDIUM" else 2
            if pat.direction == "bullish":
                score += weight
            elif pat.direction == "bearish":
                score -= weight

        detector = ChartPatternDetector(self.raw)
        for pat in detector.detect_all():
            chart.append({
                "name": pat.name,
                "direction": pat.direction,
                "confidence": pat.confidence,
                "targetMovePct": pat.target_move_pct,
                "description": pat.description,
            })
            weight = 10 if pat.confidence == "HIGH" else 6 if pat.confidence == "MEDIUM" else 3
            if pat.direction == "BULLISH":
                score += weight
            elif pat.direction == "BEARISH":
                score -= weight

        if not candlestick and not chart:
            return 0, "No major candlestick or chart pattern was detected.", [], []
        bullish = sum(1 for p in candlestick if p["direction"] == "bullish") + sum(1 for p in chart if p["direction"] == "BULLISH")
        bearish = sum(1 for p in candlestick if p["direction"] == "bearish") + sum(1 for p in chart if p["direction"] == "BEARISH")
        return score, f"Detected {bullish} bullish and {bearish} bearish pattern signal(s).", candlestick, chart


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def _bollinger(close: pd.Series, period: int = 20) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid, mid + 2 * std, mid - 2 * std


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> tuple[pd.Series, pd.Series]:
    low14 = low.rolling(period).min()
    high14 = high.rolling(period).max()
    k = ((close - low14) / (high14 - low14).replace(0, np.nan) * 100).rolling(3).mean()
    d = k.rolling(3).mean()
    return k, d


def _support_resistance(df: pd.DataFrame, price: float) -> tuple[list[float], list[float]]:
    highs = df["high"]
    lows = df["low"]
    levels: list[float] = []
    window = 4
    for i in range(window, len(df) - window):
        if highs.iloc[i] == highs.iloc[i - window: i + window + 1].max():
            levels.append(float(highs.iloc[i]))
        if lows.iloc[i] == lows.iloc[i - window: i + window + 1].min():
            levels.append(float(lows.iloc[i]))

    prev = df.iloc[-2]
    pivot = (prev["high"] + prev["low"] + prev["close"]) / 3
    levels.extend([
        pivot,
        2 * pivot - prev["high"],
        2 * pivot - prev["low"],
        pivot - (prev["high"] - prev["low"]),
        pivot + (prev["high"] - prev["low"]),
        df["low"].tail(20).min(),
        df["high"].tail(20).max(),
    ])
    clustered = _cluster_levels([v for v in levels if np.isfinite(v)])
    support = sorted([v for v in clustered if v < price], reverse=True)
    resistance = sorted([v for v in clustered if v > price])
    return support, resistance


def _build_trade_plan(
    signal: Signal,
    price: float,
    atr: float,
    support: list[float],
    resistance: list[float],
    latest: pd.Series,
) -> dict:
    nearest_support = support[0] if support else price - atr
    nearest_resistance = resistance[0] if resistance else price + atr
    ema9 = _finite_float(latest.get("ema9"), price)
    ema21 = _finite_float(latest.get("ema21"), price)
    rsi = _finite_float(latest.get("rsi"), 50)
    upper = _finite_float(latest.get("bb_upper"), price + atr)
    lower = _finite_float(latest.get("bb_lower"), price - atr)

    if signal in {"BUY", "STRONG BUY"}:
        pullback_ref = max([v for v in [nearest_support, ema9, ema21] if np.isfinite(v) and v < price], default=price - atr)
        extended = price >= upper * 0.995 or rsi >= 68 or price - pullback_ref > 1.1 * atr
        near_value = 0 <= price - pullback_ref <= 0.35 * atr
        breakout_ref = nearest_resistance if nearest_resistance <= price + 1.2 * atr else None

        if near_value and not extended:
            action = "ENTER_NOW"
            setup = "Long from value zone"
            entry = price
            zone_low = price - 0.15 * atr
            zone_high = price + 0.1 * atr
            entry_condition = "Price is already near the preferred support/EMA value area."
        elif extended:
            action = "WAIT_FOR_PULLBACK"
            setup = "Buy pullback"
            entry = pullback_ref + 0.05 * atr
            zone_low = pullback_ref - 0.15 * atr
            zone_high = pullback_ref + 0.25 * atr
            entry_condition = f"Wait for price to pull back into {_fmt(zone_low)} - {_fmt(zone_high)} instead of chasing."
        elif breakout_ref:
            action = "WAIT_FOR_BREAKOUT"
            setup = "Buy breakout"
            entry = breakout_ref + 0.1 * atr
            zone_low = entry
            zone_high = entry + 0.2 * atr
            entry_condition = f"Enter only if price breaks and holds above {_fmt(entry)}."
        else:
            action = "WAIT_FOR_PULLBACK"
            setup = "Buy pullback"
            entry = pullback_ref + 0.05 * atr
            zone_low = pullback_ref - 0.15 * atr
            zone_high = pullback_ref + 0.25 * atr
            entry_condition = f"Wait for price to revisit the value area around {_fmt(entry)}."

        stop = min(nearest_support, zone_low) - 0.5 * atr
        if stop >= entry:
            stop = entry - 1.5 * atr
        risk = max(entry - stop, atr * 0.5)
        targets = _long_targets(entry, risk, resistance)
        invalidation = f"Long thesis fails below {_fmt(stop)}."
    elif signal in {"SELL", "STRONG SELL"}:
        rebound_ref = min([v for v in [nearest_resistance, ema9, ema21] if np.isfinite(v) and v > price], default=price + atr)
        extended = price <= lower * 1.005 or rsi <= 32 or rebound_ref - price > 1.1 * atr
        near_value = 0 <= rebound_ref - price <= 0.35 * atr
        breakdown_ref = nearest_support if nearest_support >= price - 1.2 * atr else None

        if near_value and not extended:
            action = "ENTER_NOW"
            setup = "Short from resistance zone"
            entry = price
            zone_low = price - 0.1 * atr
            zone_high = price + 0.15 * atr
            entry_condition = "Price is already near the preferred resistance/EMA area."
        elif extended:
            action = "WAIT_FOR_REBOUND"
            setup = "Sell rebound"
            entry = rebound_ref - 0.05 * atr
            zone_low = rebound_ref - 0.25 * atr
            zone_high = rebound_ref + 0.15 * atr
            entry_condition = f"Wait for a rebound into {_fmt(zone_low)} - {_fmt(zone_high)} instead of selling after an extended drop."
        elif breakdown_ref:
            action = "WAIT_FOR_BREAKDOWN"
            setup = "Sell breakdown"
            entry = breakdown_ref - 0.1 * atr
            zone_low = entry - 0.2 * atr
            zone_high = entry
            entry_condition = f"Enter only if price breaks and holds below {_fmt(entry)}."
        else:
            action = "WAIT_FOR_REBOUND"
            setup = "Sell rebound"
            entry = rebound_ref - 0.05 * atr
            zone_low = rebound_ref - 0.25 * atr
            zone_high = rebound_ref + 0.15 * atr
            entry_condition = f"Wait for price to rebound toward {_fmt(entry)}."

        stop = max(nearest_resistance, zone_high) + 0.5 * atr
        if stop <= entry:
            stop = entry + 1.5 * atr
        risk = max(stop - entry, atr * 0.5)
        targets = _short_targets(entry, risk, support)
        invalidation = f"Bearish thesis fails above {_fmt(stop)}."
    else:
        bullish_bias = nearest_resistance - price <= price - nearest_support
        if bullish_bias:
            action = "WAIT_FOR_BREAKOUT"
            entry = nearest_resistance + 0.1 * atr
            stop = nearest_support - 0.35 * atr
            risk = max(entry - stop, atr)
            targets = _long_targets(entry, risk, resistance[1:])
            setup = "Wait for upside breakout"
            invalidation = f"Avoid long entries unless price breaks above {_fmt(entry)}."
            entry_condition = f"No trade now. Long trigger requires a break above {_fmt(entry)}."
        else:
            action = "WAIT_FOR_BREAKDOWN"
            entry = nearest_support - 0.1 * atr
            stop = nearest_resistance + 0.35 * atr
            risk = max(stop - entry, atr)
            targets = _short_targets(entry, risk, support[1:])
            setup = "Wait for downside breakdown"
            invalidation = f"Avoid short entries unless price breaks below {_fmt(entry)}."
            entry_condition = f"No trade now. Short trigger requires a break below {_fmt(entry)}."
        zone_low = entry - 0.2 * atr
        zone_high = entry + 0.2 * atr

    target1, target2, target3 = targets
    reward = abs(target2 - entry)
    risk_reward = reward / risk if risk else None
    return {
        "action": action,
        "setup": setup,
        "entryCondition": entry_condition,
        "isActionableNow": action == "ENTER_NOW",
        "currentPrice": _round(price),
        "entry": _round(entry),
        "entryZoneLow": _round(min(zone_low, zone_high)),
        "entryZoneHigh": _round(max(zone_low, zone_high)),
        "stopLoss": _round(stop),
        "takeProfit1": _round(target1),
        "takeProfit2": _round(target2),
        "takeProfit3": _round(target3),
        "riskReward": _round(risk_reward, 2),
        "positionNote": _position_note(signal),
        "invalidation": invalidation,
    }


def _long_targets(entry: float, risk: float, resistance: list[float]) -> tuple[float, float, float]:
    t1 = next((r for r in resistance if r > entry + 0.6 * risk), entry + 1.25 * risk)
    t2 = max(entry + 2 * risk, next((r for r in resistance if r > t1), entry + 2 * risk))
    t3 = max(entry + 3 * risk, next((r for r in resistance if r > t2), entry + 3 * risk))
    return t1, t2, t3


def _short_targets(entry: float, risk: float, support: list[float]) -> tuple[float, float, float]:
    t1 = next((s for s in support if s < entry - 0.6 * risk), entry - 1.25 * risk)
    t2 = min(entry - 2 * risk, next((s for s in support if s < t1), entry - 2 * risk))
    t3 = min(entry - 3 * risk, next((s for s in support if s < t2), entry - 3 * risk))
    return t1, t2, t3


def _signal_from_score(score: float) -> Signal:
    if score >= 50:
        return "STRONG BUY"
    if score >= 20:
        return "BUY"
    if score <= -50:
        return "STRONG SELL"
    if score <= -20:
        return "SELL"
    return "HOLD"


def _confidence(score: float, candle_count: int, evidence: list[SignalEvidence]) -> str:
    aligned = sum(1 for item in evidence if abs(item.score) >= 6 and np.sign(item.score) == np.sign(score))
    if abs(score) >= 50 and aligned >= 3 and candle_count >= 80:
        return "High"
    if abs(score) >= 24 and aligned >= 2 and candle_count >= 50:
        return "Medium"
    return "Low"


def _warnings(signal: Signal, confidence: str, candle_count: int, atr: float, price: float) -> list[str]:
    warnings = [
        "Rule-based technical signal only; review liquidity, news, earnings, and portfolio risk before acting.",
    ]
    if signal == "HOLD":
        warnings.append("No-trade signal: wait for the trigger level instead of forcing an entry.")
    if confidence == "Low":
        warnings.append("Low confidence means indicator agreement is weak or data depth is limited.")
    if candle_count < 60:
        warnings.append("Fewer than 60 candles reduces reliability for EMA50 and pattern analysis.")
    if atr / price > 0.08:
        warnings.append("ATR is high relative to price; position size should be smaller than normal.")
    return warnings


def _build_explanation(signal: Signal, confidence: str, evidence: list[SignalEvidence], plan: dict) -> str:
    drivers = sorted(evidence, key=lambda item: abs(item.score), reverse=True)[:3]
    driver_text = " ".join(f"{item.label}: {item.explanation}" for item in drivers)
    return (
        f"{signal} with {confidence.lower()} confidence. {driver_text} "
        f"Plan: {plan['setup']} around {_fmt(plan['entry'])}, stop {_fmt(plan['stopLoss'])}, "
        f"main target {_fmt(plan['takeProfit2'])}."
    )


def _volume_ratio(df: pd.DataFrame) -> float | None:
    volume = df["volume"].tail(20)
    avg = volume.mean()
    if not avg or not np.isfinite(avg):
        return None
    return float(df["volume"].iloc[-1] / avg)


def _cluster_levels(levels: list[float], tolerance_pct: float = 0.004) -> list[float]:
    if not levels:
        return []
    sorted_levels = sorted(levels)
    clusters: list[list[float]] = [[sorted_levels[0]]]
    for level in sorted_levels[1:]:
        ref = clusters[-1][-1]
        if abs(level - ref) / max(abs(ref), 1e-9) <= tolerance_pct:
            clusters[-1].append(level)
        else:
            clusters.append([level])
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _verdict(score: int) -> str:
    if score >= 8:
        return "Bullish"
    if score <= -8:
        return "Bearish"
    return "Neutral"


def _position_note(signal: Signal) -> str:
    if signal in {"STRONG BUY", "STRONG SELL"}:
        return "Higher conviction, but size from stop-loss distance rather than conviction."
    if signal in {"BUY", "SELL"}:
        return "Moderate conviction; consider partial size until price confirms."
    return "No immediate trade; use the trigger only if price confirms direction."


def _finite_float(value, fallback: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return value if np.isfinite(value) else fallback


def _round(value, digits: int = 4):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):
        return None
    return round(value, digits)


def _fmt(value) -> str:
    rounded = _round(value)
    return "N/A" if rounded is None else f"${rounded:,.4f}"
