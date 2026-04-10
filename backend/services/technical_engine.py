"""
TechnicalAnalysisEngine — Phase 1 of AI Analysis Enhancement Plan.

Takes raw OHLCV data (list of dicts with date/open/high/low/close/volume)
and computes a full indicator suite + candlestick pattern detection, then
formats it as a multi-section prompt string for injection into AI analysis.

Indicators:
  Trend:      EMA9, EMA21, EMA50, SMA200
  Momentum:   RSI(14), Stochastic(14,3), Williams %R
  MACD:       line, signal, histogram, crossover detection
  Volatility: Bollinger Bands (position %, width), ATR(14)
  Volume:     OBV trend, volume vs 20d average

Candlestick patterns (detected on last 5 candles, manual implementation
so no TA-Lib system dependency is required):
  Bullish reversal:  Hammer, Bullish Engulfing, Morning Star, Piercing Line
  Bearish reversal:  Shooting Star, Bearish Engulfing, Evening Star, Hanging Man
  Continuation:      Three White Soldiers, Three Black Crows
  Indecision:        Doji, Spinning Top

Support/Resistance:
  Standard pivot points (P, R1, R2, S1, S2)
  Swing high/low clusters over the full period
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class PatternResult:
    name: str
    candles_ago: int           # 0 = current candle, 1 = yesterday, etc.
    direction: str             # "bullish" | "bearish" | "neutral"
    significance: str          # "HIGH" | "MEDIUM" | "LOW"


@dataclass
class TechnicalContext:
    # Trend
    ema9: Optional[float] = None
    ema21: Optional[float] = None
    ema50: Optional[float] = None
    sma200: Optional[float] = None
    price_vs_ema9: str = "N/A"
    price_vs_ema21: str = "N/A"
    price_vs_ema50: str = "N/A"
    price_vs_sma200: str = "N/A"
    trend_regime: str = "UNKNOWN"

    # Momentum
    rsi: Optional[float] = None
    rsi_label: str = "N/A"
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    stoch_label: str = "N/A"
    williams_r: Optional[float] = None

    # MACD
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    macd_crossover: str = "none"      # "bullish" | "bearish" | "none"
    macd_days_since_cross: int = 0

    # Volatility
    atr: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_mid: Optional[float] = None
    bb_position_pct: Optional[float] = None   # 0-100 (0=at lower, 100=at upper)
    bb_width: Optional[float] = None

    # Volume
    volume_ratio: Optional[float] = None      # current vs 20d avg
    volume_label: str = "N/A"
    obv_trend: str = "N/A"                   # "Rising" | "Falling" | "Flat"

    # Levels
    pivot: Optional[float] = None
    r1: Optional[float] = None
    r2: Optional[float] = None
    s1: Optional[float] = None
    s2: Optional[float] = None
    swing_highs: list[float] = field(default_factory=list)
    swing_lows: list[float] = field(default_factory=list)

    # Patterns
    patterns: list[PatternResult] = field(default_factory=list)

    # Meta
    num_candles: int = 0
    current_price: Optional[float] = None


# ─── Engine ───────────────────────────────────────────────────────────────────

class TechnicalAnalysisEngine:
    """
    Compute technical indicators and candlestick patterns from OHLCV data.

    Usage:
        engine = TechnicalAnalysisEngine(ohlcv_list)
        prompt_str = engine.build_prompt_context()
    """

    def __init__(self, ohlcv: list[dict]):
        self._raw_ohlcv = ohlcv  # kept for chart pattern detector
        if not ohlcv:
            self._df = pd.DataFrame()
            self._ctx = TechnicalContext()
            return

        self._df = pd.DataFrame(ohlcv).sort_values("date").reset_index(drop=True)

        # Ensure numeric columns
        for col in ("open", "high", "low", "close", "volume"):
            if col in self._df.columns:
                self._df[col] = pd.to_numeric(self._df[col], errors="coerce")

        self._df.dropna(subset=["close"], inplace=True)
        self._ctx = TechnicalContext(num_candles=len(self._df))

        if len(self._df) >= 2:
            self._compute_all()

    # ─── Top-level compute ───────────────────────────────────────────────

    def _compute_all(self):
        self._compute_trend()
        self._compute_momentum()
        self._compute_macd()
        self._compute_volatility()
        self._compute_volume()
        self._compute_pivots()
        self._compute_swing_levels()
        self._detect_candlestick_patterns()

    # ─── Trend ───────────────────────────────────────────────────────────

    def _ema(self, series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    def _sma(self, series: pd.Series, window: int) -> pd.Series:
        return series.rolling(window=window).mean()

    def _compute_trend(self):
        close = self._df["close"]
        price = close.iloc[-1]
        self._ctx.current_price = price

        self._ctx.ema9  = self._ema(close, 9).iloc[-1]
        self._ctx.ema21 = self._ema(close, 21).iloc[-1]

        if len(close) >= 50:
            self._ctx.ema50 = self._ema(close, 50).iloc[-1]
        if len(close) >= 200:
            self._ctx.sma200 = self._sma(close, 200).iloc[-1]

        def _vs(val):
            if val is None:
                return "N/A"
            return "ABOVE (bullish)" if price > val else "BELOW (bearish)"

        self._ctx.price_vs_ema9  = _vs(self._ctx.ema9)
        self._ctx.price_vs_ema21 = _vs(self._ctx.ema21)
        self._ctx.price_vs_ema50 = _vs(self._ctx.ema50)
        self._ctx.price_vs_sma200 = _vs(self._ctx.sma200)

        # Simple regime classification
        bullish_count = sum(
            1 for v in [self._ctx.ema9, self._ctx.ema21, self._ctx.ema50]
            if v is not None and price > v
        )
        if bullish_count == 3:
            self._ctx.trend_regime = "STRONGLY BULLISH"
        elif bullish_count == 2:
            self._ctx.trend_regime = "MODERATELY BULLISH"
        elif bullish_count == 1:
            self._ctx.trend_regime = "MODERATELY BEARISH"
        else:
            self._ctx.trend_regime = "STRONGLY BEARISH"

    # ─── Momentum ────────────────────────────────────────────────────────

    def _compute_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _compute_momentum(self):
        close = self._df["close"]
        high  = self._df["high"]  if "high"  in self._df.columns else close
        low   = self._df["low"]   if "low"   in self._df.columns else close

        # RSI
        if len(close) >= 15:
            rsi_series = self._compute_rsi(close)
            self._ctx.rsi = round(rsi_series.iloc[-1], 1)
            r = self._ctx.rsi
            if r >= 70:
                self._ctx.rsi_label = "overbought — watch for reversal"
            elif r >= 60:
                self._ctx.rsi_label = "bullish momentum"
            elif r >= 45:
                self._ctx.rsi_label = "neutral, room to run"
            elif r >= 30:
                self._ctx.rsi_label = "bearish momentum"
            else:
                self._ctx.rsi_label = "oversold — watch for bounce"

        # Stochastic %K/%D (14,3)
        period = 14
        if len(close) >= period:
            low14  = low.rolling(period).min()
            high14 = high.rolling(period).max()
            rng = (high14 - low14).replace(0, np.nan)
            stoch_k_raw = (close - low14) / rng * 100
            stoch_k = stoch_k_raw.rolling(3).mean()
            stoch_d = stoch_k.rolling(3).mean()
            self._ctx.stoch_k = round(stoch_k.iloc[-1], 1)
            self._ctx.stoch_d = round(stoch_d.iloc[-1], 1)
            k = self._ctx.stoch_k
            if k >= 80:
                self._ctx.stoch_label = "overbought"
            elif k >= 60:
                self._ctx.stoch_label = "approaching overbought"
            elif k <= 20:
                self._ctx.stoch_label = "oversold"
            elif k <= 40:
                self._ctx.stoch_label = "approaching oversold"
            else:
                self._ctx.stoch_label = "neutral"

        # Williams %R
        period_wr = 14
        if len(close) >= period_wr:
            high_wr = high.rolling(period_wr).max()
            low_wr  = low.rolling(period_wr).min()
            rng_wr  = (high_wr - low_wr).replace(0, np.nan)
            wr = (high_wr - close) / rng_wr * -100
            self._ctx.williams_r = round(wr.iloc[-1], 1)

    # ─── MACD ────────────────────────────────────────────────────────────

    def _compute_macd(self):
        close = self._df["close"]
        if len(close) < 26:
            return
        ema12 = self._ema(close, 12)
        ema26 = self._ema(close, 26)
        macd  = ema12 - ema26
        signal = self._ema(macd, 9)
        hist  = macd - signal

        self._ctx.macd_line   = round(macd.iloc[-1], 4)
        self._ctx.macd_signal = round(signal.iloc[-1], 4)
        self._ctx.macd_hist   = round(hist.iloc[-1], 4)

        # Detect crossover in last 5 candles
        for i in range(1, min(6, len(hist))):
            idx = -i
            prev_idx = -(i + 1)
            if len(macd) > abs(prev_idx):
                curr_cross = macd.iloc[idx] > signal.iloc[idx]
                prev_cross = macd.iloc[prev_idx] > signal.iloc[prev_idx]
                if curr_cross and not prev_cross:
                    self._ctx.macd_crossover = "bullish"
                    self._ctx.macd_days_since_cross = i - 1
                    break
                elif not curr_cross and prev_cross:
                    self._ctx.macd_crossover = "bearish"
                    self._ctx.macd_days_since_cross = i - 1
                    break

    # ─── Volatility ──────────────────────────────────────────────────────

    def _compute_volatility(self):
        close = self._df["close"]
        high  = self._df["high"]  if "high"  in self._df.columns else close
        low   = self._df["low"]   if "low"   in self._df.columns else close

        # ATR(14)
        period_atr = 14
        if len(close) >= period_atr + 1:
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr = tr.ewm(com=period_atr - 1, min_periods=period_atr).mean()
            self._ctx.atr = round(atr.iloc[-1], 4)

        # Bollinger Bands (20, 2)
        period_bb = 20
        if len(close) >= period_bb:
            mid  = self._sma(close, period_bb)
            std  = close.rolling(period_bb).std()
            upper = mid + 2 * std
            lower = mid - 2 * std
            price = close.iloc[-1]
            u = upper.iloc[-1]
            l = lower.iloc[-1]
            m = mid.iloc[-1]
            self._ctx.bb_upper = round(u, 4)
            self._ctx.bb_lower = round(l, 4)
            self._ctx.bb_mid   = round(m, 4)
            rng = u - l
            if rng > 0:
                self._ctx.bb_position_pct = round((price - l) / rng * 100, 1)
                self._ctx.bb_width = round(rng / m, 4)

    # ─── Volume ──────────────────────────────────────────────────────────

    def _compute_volume(self):
        if "volume" not in self._df.columns:
            return
        vol = self._df["volume"].fillna(0)
        if len(vol) < 2:
            return

        # Volume ratio: today vs 20d avg
        avg20 = vol.rolling(min(20, len(vol))).mean().iloc[-1]
        if avg20 and avg20 > 0:
            ratio = vol.iloc[-1] / avg20
            self._ctx.volume_ratio = round(ratio, 2)
            if ratio >= 2.0:
                self._ctx.volume_label = "very elevated (strong conviction)"
            elif ratio >= 1.4:
                self._ctx.volume_label = "elevated (confirms move)"
            elif ratio >= 0.8:
                self._ctx.volume_label = "average"
            else:
                self._ctx.volume_label = "below average (weak conviction)"

        # OBV trend: compare last OBV value vs 10 days ago
        close = self._df["close"]
        obv = (np.sign(close.diff()).fillna(0) * vol).cumsum()
        if len(obv) >= 10:
            obv_now  = obv.iloc[-1]
            obv_prev = obv.iloc[-10]
            change_pct = (obv_now - obv_prev) / max(abs(obv_prev), 1) * 100
            if change_pct > 5:
                self._ctx.obv_trend = "Rising (accumulation)"
            elif change_pct < -5:
                self._ctx.obv_trend = "Falling (distribution)"
            else:
                self._ctx.obv_trend = "Flat (no strong trend)"

    # ─── Pivot Points ────────────────────────────────────────────────────

    def _compute_pivots(self):
        """Standard pivot points based on the last completed daily candle."""
        if len(self._df) < 2:
            return
        prev = self._df.iloc[-2]
        h = prev.get("high", prev["close"])
        l = prev.get("low",  prev["close"])
        c = prev["close"]
        p  = (h + l + c) / 3
        r1 = 2 * p - l
        r2 = p + (h - l)
        s1 = 2 * p - h
        s2 = p - (h - l)
        self._ctx.pivot = round(p,  4)
        self._ctx.r1    = round(r1, 4)
        self._ctx.r2    = round(r2, 4)
        self._ctx.s1    = round(s1, 4)
        self._ctx.s2    = round(s2, 4)

    # ─── Swing Highs / Lows ──────────────────────────────────────────────

    def _compute_swing_levels(self, window: int = 5):
        """Find local swing highs and lows using a rolling window."""
        if len(self._df) < window * 2 + 1:
            return

        highs = self._df["high"]  if "high" in self._df.columns else self._df["close"]
        lows  = self._df["low"]   if "low"  in self._df.columns else self._df["close"]

        swing_h = []
        swing_l = []
        for i in range(window, len(self._df) - window):
            if highs.iloc[i] == highs.iloc[i - window: i + window + 1].max():
                swing_h.append(round(float(highs.iloc[i]), 4))
            if lows.iloc[i] == lows.iloc[i - window: i + window + 1].min():
                swing_l.append(round(float(lows.iloc[i]), 4))

        # Cluster nearby levels (within 0.5% of each other)
        self._ctx.swing_highs = _cluster_levels(swing_h)[-4:]   # top 4
        self._ctx.swing_lows  = _cluster_levels(swing_l)[:4]    # bottom 4

    # ─── Candlestick Patterns ────────────────────────────────────────────

    def _detect_candlestick_patterns(self):
        """Detect classic candlestick patterns on the last 5 candles (no TA-Lib needed)."""
        df = self._df
        if len(df) < 3:
            return

        patterns: list[PatternResult] = []
        n = len(df)

        for i in range(max(0, n - 5), n):
            candles_ago = n - 1 - i
            row = df.iloc[i]
            o, h, l, c = row.get("open", row["close"]), row.get("high", row["close"]), row.get("low", row["close"]), row["close"]
            body    = abs(c - o)
            full_rng = h - l
            if full_rng == 0:
                continue

            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            body_pct   = body / full_rng

            is_bullish_candle = c > o
            is_bearish_candle = c < o

            # ── Single-candle patterns ─────────────────────────────────

            # Doji: body < 10% of range
            if body_pct < 0.10:
                patterns.append(PatternResult("Doji", candles_ago, "neutral", "MEDIUM"))

            # Hammer: small body in top 30%, long lower wick (>2x body), tiny upper wick
            elif (
                lower_wick >= 2 * body
                and upper_wick <= 0.3 * body
                and (c - l) / full_rng >= 0.6
                and is_bullish_candle
            ):
                patterns.append(PatternResult("Hammer", candles_ago, "bullish", "HIGH"))

            # Shooting Star: small body in bottom 30%, long upper wick
            elif (
                upper_wick >= 2 * body
                and lower_wick <= 0.3 * body
                and (h - c) / full_rng >= 0.6
                and is_bearish_candle
            ):
                patterns.append(PatternResult("Shooting Star", candles_ago, "bearish", "HIGH"))

            # Spinning Top: small body (10-30%) with both wicks
            elif 0.10 < body_pct < 0.30 and upper_wick > body and lower_wick > body:
                patterns.append(PatternResult("Spinning Top", candles_ago, "neutral", "LOW"))

        # ── Two-candle patterns ───────────────────────────────────────

        for i in range(max(1, n - 5), n):
            candles_ago = n - 1 - i
            prev = df.iloc[i - 1]
            curr = df.iloc[i]

            po, ph, pl, pc = prev.get("open", prev["close"]), prev.get("high", prev["close"]), prev.get("low", prev["close"]), prev["close"]
            co, ch, cl, cc = curr.get("open", curr["close"]), curr.get("high", curr["close"]), curr.get("low", curr["close"]), curr["close"]

            prev_bearish = pc < po
            prev_bullish = pc > po
            curr_bullish = cc > co
            curr_bearish = cc < co

            # Bullish Engulfing
            if (
                prev_bearish and curr_bullish
                and co <= pc and cc >= po
                and abs(cc - co) > abs(pc - po)
            ):
                patterns.append(PatternResult("Bullish Engulfing", candles_ago, "bullish", "HIGH"))

            # Bearish Engulfing
            elif (
                prev_bullish and curr_bearish
                and co >= pc and cc <= po
                and abs(co - cc) > abs(po - pc)
            ):
                patterns.append(PatternResult("Bearish Engulfing", candles_ago, "bearish", "HIGH"))

            # Piercing Line
            elif (
                prev_bearish and curr_bullish
                and co < pl
                and cc > (po + pc) / 2
                and cc < po
            ):
                patterns.append(PatternResult("Piercing Line", candles_ago, "bullish", "MEDIUM"))

            # Dark Cloud Cover
            elif (
                prev_bullish and curr_bearish
                and co > ph
                and cc < (po + pc) / 2
                and cc > po
            ):
                patterns.append(PatternResult("Dark Cloud Cover", candles_ago, "bearish", "MEDIUM"))

        # ── Three-candle patterns ─────────────────────────────────────

        if n >= 3:
            for i in range(max(2, n - 4), n):
                candles_ago = n - 1 - i
                a = df.iloc[i - 2]
                b = df.iloc[i - 1]
                c_ = df.iloc[i]

                ao, ac = a.get("open", a["close"]), a["close"]
                bo, bc = b.get("open", b["close"]), b["close"]
                co2, cc2 = c_.get("open", c_["close"]), c_["close"]

                # Three White Soldiers
                if (
                    ac > ao and bc > bo and cc2 > co2   # all bullish
                    and bc > ac and cc2 > bc             # consecutive higher closes
                    and bo > ao and co2 > bo             # opens within prev body
                ):
                    patterns.append(PatternResult("Three White Soldiers", candles_ago, "bullish", "HIGH"))

                # Three Black Crows
                elif (
                    ac < ao and bc < bo and cc2 < co2   # all bearish
                    and bc < ac and cc2 < bc             # consecutive lower closes
                    and bo < ao and co2 < bo             # opens within prev body
                ):
                    patterns.append(PatternResult("Three Black Crows", candles_ago, "bearish", "HIGH"))

                # Morning Star
                elif (
                    ac < ao                              # first candle bearish
                    and abs(bc - bo) / max(abs(a["high"] - a["low"]), 1e-9) < 0.2  # second small
                    and cc2 > co2                        # third bullish
                    and cc2 > (ao + ac) / 2              # closes above midpoint of first
                ):
                    patterns.append(PatternResult("Morning Star", candles_ago, "bullish", "HIGH"))

                # Evening Star
                elif (
                    ac > ao                              # first candle bullish
                    and abs(bc - bo) / max(abs(a["high"] - a["low"]), 1e-9) < 0.2  # second small
                    and cc2 < co2                        # third bearish
                    and cc2 < (ao + ac) / 2              # closes below midpoint of first
                ):
                    patterns.append(PatternResult("Evening Star", candles_ago, "bearish", "HIGH"))

        self._ctx.patterns = patterns

    # ─── Prompt builder ──────────────────────────────────────────────────

    def build_prompt_context(self) -> str:
        """Return a formatted multi-section string for injection into AI prompts."""
        ctx = self._ctx
        if ctx.num_candles < 5:
            return ""

        lines: list[str] = [
            f"\n=== Technical Analysis (computed from {ctx.num_candles} trading days of real OHLCV data) ===",
            "",
            "TREND",
        ]

        def _fmt_price(v):
            if v is None:
                return "N/A (insufficient data)"
            return f"${v:,.4f}"

        lines += [
            f"  Price vs EMA9  : {_fmt_price(ctx.ema9)} — {ctx.price_vs_ema9}",
            f"  Price vs EMA21 : {_fmt_price(ctx.ema21)} — {ctx.price_vs_ema21}",
            f"  Price vs EMA50 : {_fmt_price(ctx.ema50)} — {ctx.price_vs_ema50}",
            f"  Price vs SMA200: {_fmt_price(ctx.sma200)} — {ctx.price_vs_sma200}",
            f"  Trend regime   : {ctx.trend_regime}",
        ]

        lines += ["", "MOMENTUM"]
        if ctx.rsi is not None:
            lines.append(f"  RSI(14)        : {ctx.rsi} — {ctx.rsi_label}")
        if ctx.stoch_k is not None:
            lines.append(f"  Stochastic %K/%D: {ctx.stoch_k} / {ctx.stoch_d} — {ctx.stoch_label}")
        if ctx.williams_r is not None:
            lines.append(f"  Williams %R    : {ctx.williams_r}")

        lines += ["", "MACD"]
        if ctx.macd_line is not None:
            lines.append(f"  MACD line / signal / hist: {ctx.macd_line} / {ctx.macd_signal} / {ctx.macd_hist}")
            if ctx.macd_crossover != "none":
                ago = f"{ctx.macd_days_since_cross} day(s) ago" if ctx.macd_days_since_cross > 0 else "today"
                lines.append(f"  Crossover: {ctx.macd_crossover.upper()} ({ago})")
            else:
                hist_dir = "expanding bullish" if ctx.macd_hist and ctx.macd_hist > 0 else "expanding bearish" if ctx.macd_hist and ctx.macd_hist < 0 else "flat"
                lines.append(f"  Histogram: {hist_dir} (no recent crossover)")
        else:
            lines.append("  N/A (insufficient data)")

        lines += ["", "VOLATILITY"]
        if ctx.atr is not None:
            lines.append(f"  ATR(14)        : ${ctx.atr:,.4f} (expected daily range)")
        if ctx.bb_position_pct is not None:
            lines.append(f"  BB position    : {ctx.bb_position_pct}th percentile "
                         f"(upper ${ctx.bb_upper:,.4f} / lower ${ctx.bb_lower:,.4f})")
            lines.append(f"  BB width       : {ctx.bb_width:.4f} "
                         f"({'wide — high volatility' if ctx.bb_width > 0.12 else 'narrow — low volatility / potential breakout'})")

        lines += ["", "VOLUME"]
        if ctx.volume_ratio is not None:
            lines.append(f"  vs 20d average : {ctx.volume_ratio}× — {ctx.volume_label}")
        lines.append(f"  OBV trend      : {ctx.obv_trend}")

        lines += ["", "KEY LEVELS"]
        if ctx.pivot:
            lines.append(f"  Pivot (daily)  : ${ctx.pivot:,.4f} | R1: ${ctx.r1:,.4f} | R2: ${ctx.r2:,.4f}")
            lines.append(f"  S1: ${ctx.s1:,.4f} | S2: ${ctx.s2:,.4f}")
        if ctx.swing_highs:
            levels = ", ".join(f"${v:,.4f}" for v in sorted(ctx.swing_highs))
            lines.append(f"  Swing resistance: {levels}")
        if ctx.swing_lows:
            levels = ", ".join(f"${v:,.4f}" for v in sorted(ctx.swing_lows))
            lines.append(f"  Swing support  : {levels}")

        if ctx.patterns:
            lines += ["", "CANDLESTICK PATTERNS (last 5 candles)"]
            order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            sorted_pats = sorted(ctx.patterns, key=lambda p: (order.get(p.significance, 3), p.candles_ago))
            for pat in sorted_pats:
                ago_str = "current candle" if pat.candles_ago == 0 else f"{pat.candles_ago} candle(s) ago"
                lines.append(f"  {pat.name} — {ago_str} ({pat.direction.upper()}, {pat.significance} SIGNIFICANCE)")
        else:
            lines += ["", "CANDLESTICK PATTERNS (last 5 candles)", "  None detected"]

        # ── Chart patterns (rule-based, longer timeframe) ─────────────────────
        try:
            from services.chart_patterns import ChartPatternDetector
            detector = ChartPatternDetector(self._raw_ohlcv)
            chart_str = detector.to_prompt_string()
            if chart_str:
                lines.append(chart_str)
        except Exception:
            pass  # Chart patterns are additive — don't fail the main context

        lines += [
            "",
            "IMPORTANT: The above is real computed data. Use it as ground truth.",
            "Do NOT invent price levels — all targets/stops must be derived from the data above.",
        ]

        return "\n".join(lines)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _cluster_levels(levels: list[float], tolerance_pct: float = 0.005) -> list[float]:
    """Merge nearby price levels within tolerance_pct of each other."""
    if not levels:
        return []
    sorted_levels = sorted(levels)
    clusters: list[list[float]] = [[sorted_levels[0]]]
    for lvl in sorted_levels[1:]:
        ref = clusters[-1][-1]
        if abs(lvl - ref) / max(ref, 1e-9) <= tolerance_pct:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])
    return [round(sum(c) / len(c), 4) for c in clusters]
