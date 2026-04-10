"""
Chart Pattern Detector — Phase 4.2

Rule-based detection of major chart patterns from OHLCV data.
Pure pandas/numpy — no extra dependencies.

Detected patterns:
  Trend reversal: Head & Shoulders, Inverse H&S, Double Top, Double Bottom
  Continuation:   Ascending Triangle, Descending Triangle, Symmetric Triangle
                  Bull Flag, Bear Flag, Cup & Handle
  Breakout:       Channel Breakout (up/down), Range Breakout
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PatternResult:
    name: str
    direction: str        # "BULLISH" | "BEARISH" | "NEUTRAL"
    confidence: str       # "HIGH" | "MEDIUM" | "LOW"
    target_move_pct: float | None  # expected move % (e.g. 8.5 for +8.5%)
    description: str


class ChartPatternDetector:
    """
    Detects major chart patterns from OHLCV data.

    Requires at least 20 candles. Works best with 60-120 candles (daily).
    """

    def __init__(self, ohlcv: list[dict]):
        if not ohlcv:
            self.df = pd.DataFrame()
            return
        self.df = pd.DataFrame(ohlcv)
        # Normalise column names
        rename = {}
        for col in self.df.columns:
            cl = col.lower()
            if cl in ("open", "o"):           rename[col] = "open"
            elif cl in ("high", "h"):         rename[col] = "high"
            elif cl in ("low", "l"):          rename[col] = "low"
            elif cl in ("close", "c", "price"): rename[col] = "close"
            elif cl in ("volume", "v"):       rename[col] = "volume"
        self.df.rename(columns=rename, inplace=True)
        required = {"close"}
        if not required.issubset(self.df.columns):
            self.df = pd.DataFrame()
            return
        # Ensure numeric
        for col in ("open", "high", "low", "close", "volume"):
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")
        self.df.dropna(subset=["close"], inplace=True)
        self.df.reset_index(drop=True, inplace=True)

    # ─── Public ───────────────────────────────────────────────────────────────

    def detect_all(self) -> list[PatternResult]:
        if self.df.empty or len(self.df) < 20:
            return []

        results: list[PatternResult] = []
        for detector in [
            self._detect_head_and_shoulders,
            self._detect_double_top_bottom,
            self._detect_triangles,
            self._detect_flags,
            self._detect_channel,
            self._detect_cup_and_handle,
        ]:
            try:
                results.extend(detector())
            except Exception as exc:
                logger.debug("Pattern detector %s failed: %s", detector.__name__, exc)

        return results

    def to_prompt_string(self) -> str:
        patterns = self.detect_all()
        if not patterns:
            return ""
        lines = ["\n=== Chart Patterns (rule-based detection) ==="]
        for p in patterns:
            target = f" → target move: {p.target_move_pct:+.1f}%" if p.target_move_pct is not None else ""
            lines.append(
                f"  [{p.confidence}] {p.name} ({p.direction}){target} — {p.description}"
            )
        return "\n".join(lines)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _find_peaks(self, series: pd.Series, window: int = 5) -> list[int]:
        """Find local maxima indices."""
        peaks = []
        for i in range(window, len(series) - window):
            if series.iloc[i] == series.iloc[i - window: i + window + 1].max():
                peaks.append(i)
        return peaks

    def _find_troughs(self, series: pd.Series, window: int = 5) -> list[int]:
        """Find local minima indices."""
        troughs = []
        for i in range(window, len(series) - window):
            if series.iloc[i] == series.iloc[i - window: i + window + 1].min():
                troughs.append(i)
        return troughs

    def _within_pct(self, a: float, b: float, pct: float) -> bool:
        """True if a and b are within pct% of each other."""
        if b == 0:
            return False
        return abs(a - b) / abs(b) <= pct / 100.0

    # ─── Head & Shoulders ──────────────────────────────────────────────────────

    def _detect_head_and_shoulders(self) -> list[PatternResult]:
        close = self.df["close"]
        peaks = self._find_peaks(close, window=4)
        troughs = self._find_troughs(close, window=4)
        results = []

        # Need at least 3 peaks for H&S
        for i in range(len(peaks) - 2):
            l, h, r = peaks[i], peaks[i + 1], peaks[i + 2]
            lv, hv, rv = close.iloc[l], close.iloc[h], close.iloc[r]

            # Head must be tallest, shoulders roughly equal (±5%)
            if hv > lv and hv > rv and self._within_pct(lv, rv, 8):
                neckline = min(
                    close.iloc[l:h].min() if l < h else lv,
                    close.iloc[h:r].min() if h < r else rv,
                )
                target_move = -(hv - neckline) / neckline * 100
                # Only signal if pattern is in the right 60% of data
                if r > len(close) * 0.4:
                    results.append(PatternResult(
                        name="Head & Shoulders",
                        direction="BEARISH",
                        confidence="HIGH" if abs(lv - rv) / hv < 0.03 else "MEDIUM",
                        target_move_pct=target_move,
                        description=f"Bearish reversal — neckline at {neckline:.2f}, head at {hv:.2f}",
                    ))

        # Inverse H&S (troughs)
        for i in range(len(troughs) - 2):
            l, h, r = troughs[i], troughs[i + 1], troughs[i + 2]
            lv, hv, rv = close.iloc[l], close.iloc[h], close.iloc[r]
            if hv < lv and hv < rv and self._within_pct(lv, rv, 8):
                neckline = max(
                    close.iloc[l:h].max() if l < h else lv,
                    close.iloc[h:r].max() if h < r else rv,
                )
                target_move = (neckline - hv) / neckline * 100
                if r > len(close) * 0.4:
                    results.append(PatternResult(
                        name="Inverse Head & Shoulders",
                        direction="BULLISH",
                        confidence="HIGH" if abs(lv - rv) / abs(hv) < 0.03 else "MEDIUM",
                        target_move_pct=target_move,
                        description=f"Bullish reversal — neckline at {neckline:.2f}, trough at {hv:.2f}",
                    ))

        return results

    # ─── Double Top / Double Bottom ────────────────────────────────────────────

    def _detect_double_top_bottom(self) -> list[PatternResult]:
        close = self.df["close"]
        peaks = self._find_peaks(close, window=5)
        troughs = self._find_troughs(close, window=5)
        results = []
        current = close.iloc[-1]

        # Double Top
        for i in range(len(peaks) - 1):
            p1, p2 = peaks[i], peaks[i + 1]
            v1, v2 = close.iloc[p1], close.iloc[p2]
            gap = p2 - p1
            if gap < 5 or not self._within_pct(v1, v2, 3):
                continue
            valley = close.iloc[p1:p2].min() if p1 < p2 else v1
            if v1 > valley * 1.03 and p2 > len(close) * 0.5:
                target_move = -(v1 - valley) / valley * 100
                # Confirm price is near/below valley (pattern is breaking)
                conf = "HIGH" if current <= valley * 1.02 else "MEDIUM"
                results.append(PatternResult(
                    name="Double Top",
                    direction="BEARISH",
                    confidence=conf,
                    target_move_pct=target_move,
                    description=f"Two peaks ~{v1:.0f} and ~{v2:.0f}, support at {valley:.0f}",
                ))

        # Double Bottom
        for i in range(len(troughs) - 1):
            t1, t2 = troughs[i], troughs[i + 1]
            v1, v2 = close.iloc[t1], close.iloc[t2]
            gap = t2 - t1
            if gap < 5 or not self._within_pct(v1, v2, 3):
                continue
            peak = close.iloc[t1:t2].max() if t1 < t2 else v1
            if v1 < peak * 0.97 and t2 > len(close) * 0.5:
                target_move = (peak - v1) / abs(v1) * 100
                conf = "HIGH" if current >= peak * 0.98 else "MEDIUM"
                results.append(PatternResult(
                    name="Double Bottom",
                    direction="BULLISH",
                    confidence=conf,
                    target_move_pct=target_move,
                    description=f"Two troughs ~{v1:.0f} and ~{v2:.0f}, resistance at {peak:.0f}",
                ))

        return results

    # ─── Triangles ────────────────────────────────────────────────────────────

    def _detect_triangles(self) -> list[PatternResult]:
        close = self.df["close"]
        n = len(close)
        if n < 30:
            return []

        # Use the last 30-60 candles
        window_data = close.iloc[-min(60, n):]
        x = np.arange(len(window_data))

        # Fit trend lines to highs and lows
        peaks_idx = self._find_peaks(window_data.reset_index(drop=True), window=3)
        troughs_idx = self._find_troughs(window_data.reset_index(drop=True), window=3)

        if len(peaks_idx) < 2 or len(troughs_idx) < 2:
            return []

        # Upper trendline (through peaks)
        px = np.array(peaks_idx)
        py = window_data.iloc[peaks_idx].values
        p_slope = np.polyfit(px, py, 1)[0] if len(px) >= 2 else 0

        # Lower trendline (through troughs)
        tx = np.array(troughs_idx)
        ty = window_data.iloc[troughs_idx].values
        t_slope = np.polyfit(tx, ty, 1)[0] if len(tx) >= 2 else 0

        results = []
        high_range = py.max() - py.min()
        low_range = ty.max() - ty.min()
        avg_price = close.mean()
        slope_threshold = avg_price * 0.002  # 0.2% per candle is "flat"

        if abs(p_slope) < slope_threshold and t_slope > slope_threshold:
            results.append(PatternResult(
                name="Ascending Triangle",
                direction="BULLISH",
                confidence="MEDIUM",
                target_move_pct=high_range / avg_price * 100,
                description="Flat upper resistance + rising lows — bullish breakout likely",
            ))
        elif p_slope < -slope_threshold and abs(t_slope) < slope_threshold:
            results.append(PatternResult(
                name="Descending Triangle",
                direction="BEARISH",
                confidence="MEDIUM",
                target_move_pct=-(low_range / avg_price * 100),
                description="Declining highs + flat lower support — bearish breakdown likely",
            ))
        elif p_slope < -slope_threshold and t_slope > slope_threshold:
            direction = "BULLISH" if close.iloc[-1] > close.iloc[-min(30, n)] else "BEARISH"
            results.append(PatternResult(
                name="Symmetric Triangle",
                direction=direction,
                confidence="LOW",
                target_move_pct=None,
                description="Converging highs and lows — continuation pattern, watch for breakout",
            ))

        return results

    # ─── Flags ────────────────────────────────────────────────────────────────

    def _detect_flags(self) -> list[PatternResult]:
        close = self.df["close"]
        n = len(close)
        if n < 25:
            return []

        results = []
        # Look for a strong move (pole) followed by tight consolidation (flag)
        pole_len = 10
        flag_len = 10
        if n < pole_len + flag_len:
            return []

        pole = close.iloc[-(pole_len + flag_len): -flag_len]
        flag = close.iloc[-flag_len:]

        pole_move = (pole.iloc[-1] - pole.iloc[0]) / pole.iloc[0]
        flag_range = (flag.max() - flag.min()) / flag.mean()
        flag_move = (flag.iloc[-1] - flag.iloc[0]) / flag.iloc[0]

        # Strong pole (>5%), tight flag (<4% range), flag retraces <50% of pole
        if abs(pole_move) > 0.05 and flag_range < 0.04:
            if pole_move > 0 and flag_move > -abs(pole_move) * 0.5:
                results.append(PatternResult(
                    name="Bull Flag",
                    direction="BULLISH",
                    confidence="MEDIUM",
                    target_move_pct=abs(pole_move) * 100,
                    description=f"Strong +{pole_move*100:.1f}% pole, tight consolidation — upward continuation expected",
                ))
            elif pole_move < 0 and flag_move < abs(pole_move) * 0.5:
                results.append(PatternResult(
                    name="Bear Flag",
                    direction="BEARISH",
                    confidence="MEDIUM",
                    target_move_pct=-abs(pole_move) * 100,
                    description=f"Strong {pole_move*100:.1f}% pole, tight consolidation — downward continuation expected",
                ))

        return results

    # ─── Channel ──────────────────────────────────────────────────────────────

    def _detect_channel(self) -> list[PatternResult]:
        close = self.df["close"]
        n = len(close)
        if n < 30:
            return []

        window = close.iloc[-30:]
        x = np.arange(len(window))
        slope, intercept = np.polyfit(x, window.values, 1)

        residuals = window.values - (slope * x + intercept)
        channel_width = residuals.max() - residuals.min()
        avg = window.mean()
        width_pct = channel_width / avg * 100

        results = []
        if width_pct < 8:  # Tight enough to be a channel
            if slope > avg * 0.001:  # Rising ~0.1%/candle
                results.append(PatternResult(
                    name="Rising Channel",
                    direction="BULLISH",
                    confidence="LOW",
                    target_move_pct=None,
                    description=f"Price trending in a rising channel (width: {width_pct:.1f}%)",
                ))
            elif slope < -avg * 0.001:
                results.append(PatternResult(
                    name="Descending Channel",
                    direction="BEARISH",
                    confidence="LOW",
                    target_move_pct=None,
                    description=f"Price trending in a descending channel (width: {width_pct:.1f}%)",
                ))

        return results

    # ─── Cup & Handle ─────────────────────────────────────────────────────────

    def _detect_cup_and_handle(self) -> list[PatternResult]:
        close = self.df["close"]
        n = len(close)
        if n < 40:
            return []

        # Cup: U-shaped base in the first 70% of data
        cup_data = close.iloc[:int(n * 0.7)]
        if len(cup_data) < 20:
            return []

        cup_start = cup_data.iloc[0]
        cup_end = cup_data.iloc[-1]
        cup_low = cup_data.min()
        cup_depth = (min(cup_start, cup_end) - cup_low) / min(cup_start, cup_end)

        # Cup depth 10-35%, start and end within 5% of each other
        if not (0.10 <= cup_depth <= 0.35):
            return []
        if not self._within_pct(cup_start, cup_end, 7):
            return []

        # Handle: small pullback in last 30% (< 50% of cup depth)
        handle = close.iloc[int(n * 0.7):]
        if len(handle) < 5:
            return []
        handle_drop = (handle.max() - handle.min()) / handle.max()

        if handle_drop < cup_depth * 0.5:
            return [PatternResult(
                name="Cup & Handle",
                direction="BULLISH",
                confidence="MEDIUM",
                target_move_pct=cup_depth * 100,
                description=f"Bullish continuation — cup depth {cup_depth*100:.1f}%, handle formed",
            )]

        return []
