"""
AI Portfolio Advisor Service — multi-provider, portfolio-context-aware.

Pre-fetches the user's holdings and injects them into the system prompt so
the LLM always has full portfolio context without needing tool-use round trips.

Supported providers: gemini (default), claude, openai, ollama, lmstudio
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services.portfolio_engine import PortfolioEngine
from services.analytics_engine import AnalyticsEngine
from services.market_data_service import MarketDataService
from shared.models import AdvisorConversation, User

logger = logging.getLogger(__name__)
settings = get_settings()

Provider = str  # "claude" | "openai" | "gemini" | "ollama" | "lmstudio"

_SYSTEM_TEMPLATE = """You are an expert investment intelligence assistant for a personal fintech platform.
You have deep knowledge of equities, crypto, ETFs, portfolio management, and Australian tax rules (CGT discount, FIFO/LIFO, ATO financial year July-June).

{portfolio_block}

## Your capabilities:
- Analyse portfolio composition, concentration, sector exposure, and geographic diversification
- Identify risks: overconcentration, high-volatility assets, currency exposure (AUD/USD)
- Interpret performance: unrealised P&L, cost basis, position sizing
- Suggest tax-loss harvesting (Australian CGT rules apply)
- Compare allocation to common benchmarks (ASX200, S&P500, BTC dominance)
- Suggest rebalancing, hedging ideas, and position management

## Behaviour:
1. Reference the portfolio data above specifically — mention actual symbols, values, weights
2. Be quantitative: use real numbers from the data
3. Keep responses focused and actionable
4. Use markdown formatting (headings, bullet points, bold for key figures)
5. Flag risks clearly but constructively

⚠️ Always end any response containing recommendations with:
"_This analysis is for informational purposes only and does not constitute financial advice. Consult a licensed financial advisor before making investment decisions._"
"""


@dataclass
class AdvisorResponse:
    content: str
    session_id: str
    tool_calls: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class AIAdvisorService:
    def __init__(
        self,
        db: AsyncSession,
        portfolio_engine: PortfolioEngine,
        analytics_engine: AnalyticsEngine,
        market_data: MarketDataService,
        tax_engine,
    ):
        self.db = db
        self.portfolio_engine = portfolio_engine
        self.analytics_engine = analytics_engine
        self.market_data = market_data
        self.tax_engine = tax_engine

    async def chat(
        self,
        user: User,
        message: str,
        session_id: Optional[str] = None,
        provider: str = "gemini",
    ) -> AdvisorResponse:
        from services.agents._base import call_chat_llm

        # Load/create conversation
        conversation = await self._get_or_create_conversation(user, session_id)
        # Keep only plain-text messages (filter out any legacy tool-use blocks)
        messages = [
            m for m in conversation.messages
            if isinstance(m.get("content"), str)
            and m.get("role") in ("user", "assistant")
        ]

        # Pre-fetch portfolio context (fresh on every turn)
        portfolio_block = await self._build_portfolio_block(user)
        system = _SYSTEM_TEMPLATE.format(portfolio_block=portfolio_block)

        # Append the new user message
        messages.append({"role": "user", "content": message})

        try:
            response_text = await call_chat_llm(
                messages=messages,
                system=system,
                provider=provider,  # type: ignore[arg-type]
                max_tokens=2000,
            )
        except (ValueError, RuntimeError) as exc:
            raise

        # Save
        messages.append({"role": "assistant", "content": response_text})
        conversation.messages = messages
        conversation.last_active_at = datetime.now(timezone.utc)
        if not conversation.title and message:
            conversation.title = message[:60] + ("..." if len(message) > 60 else "")
        await self.db.commit()

        return AdvisorResponse(
            content=response_text,
            session_id=conversation.id,
        )

    # ─── Portfolio context builder ────────────────────────────────────────────

    async def _build_portfolio_block(self, user: User) -> str:
        try:
            summary = await self.portfolio_engine.get_portfolio_summary(
                user_id=user.id,
                account_ids=None,
                cost_basis_method=getattr(user, "cost_basis_method", "FIFO"),
            )
        except Exception as exc:
            logger.warning("Portfolio fetch failed for advisor context: %s", exc)
            return "## Portfolio\n_Portfolio data unavailable — answer based on general knowledge._"

        if not summary.holdings:
            return "## Portfolio\n_No holdings found. The user's portfolio appears to be empty._"

        total_value = float(summary.total_market_value or 0)
        total_cost  = float(summary.total_cost_basis or 0)
        total_gain  = float(summary.total_unrealized_gain or 0)
        gain_pct    = float(summary.total_unrealized_gain_pct or 0)

        lines = [
            "## Current Portfolio",
            f"- **Total Value:** ${total_value:,.2f} AUD",
            f"- **Total Cost Basis:** ${total_cost:,.2f} AUD",
            f"- **Unrealised P&L:** ${total_gain:+,.2f} ({gain_pct:+.2f}%)",
            f"- **Positions:** {len(summary.holdings)}",
            "",
            "| # | Symbol | Class | Qty | Avg Cost | Mkt Value | Weight | P&L |",
            "|---|--------|-------|-----|----------|-----------|--------|-----|",
        ]
        sorted_holdings = sorted(summary.holdings, key=lambda h: float(h.market_value or 0), reverse=True)
        for i, h in enumerate(sorted_holdings, 1):
            mv     = float(h.market_value or 0)
            avg    = float(h.average_cost_basis or 0)
            pnl    = float(h.unrealized_gain or 0)
            pnl_pct= float(h.unrealized_gain_pct or 0)
            weight = (mv / total_value * 100) if total_value else 0
            lines.append(
                f"| {i} | **{h.symbol}** | {h.asset_class} | {float(h.quantity):.4f} "
                f"| ${avg:,.2f} | ${mv:,.2f} | {weight:.1f}% | {pnl:+,.2f} ({pnl_pct:+.1f}%) |"
            )

        # Asset class summary
        by_class: dict[str, float] = {}
        for h in summary.holdings:
            cls = h.asset_class or "OTHER"
            by_class[cls] = by_class.get(cls, 0) + float(h.market_value or 0)
        lines.append("")
        lines.append("**Allocation by asset class:**")
        for cls, mv in sorted(by_class.items(), key=lambda x: -x[1]):
            pct = (mv / total_value * 100) if total_value else 0
            lines.append(f"- {cls}: ${mv:,.2f} ({pct:.1f}%)")

        return "\n".join(lines)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    async def _get_or_create_conversation(
        self, user: User, session_id: Optional[str]
    ) -> AdvisorConversation:
        from sqlalchemy import select

        if session_id:
            result = await self.db.execute(
                select(AdvisorConversation).where(
                    AdvisorConversation.id == session_id,
                    AdvisorConversation.user_id == user.id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv:
                return conv

        conv = AdvisorConversation(user_id=user.id, messages=[])
        self.db.add(conv)
        await self.db.flush()
        return conv
