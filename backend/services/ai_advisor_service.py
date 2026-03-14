"""
AI Portfolio Advisor Service.

Uses Claude with tool use to answer investment questions with live portfolio data.
Implements an agentic loop: Claude can call tools to fetch portfolio data,
prices, analytics, and tax estimates before synthesizing a response.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services.portfolio_engine import PortfolioEngine
from services.analytics_engine import AnalyticsEngine
from services.market_data_service import MarketDataService
from services.tax_engine import TaxEngine
from shared.models import AdvisorConversation, User

logger = logging.getLogger(__name__)
settings = get_settings()

TOOL_DEFINITIONS = [
    {
        "name": "get_portfolio_holdings",
        "description": (
            "Fetch the user's current portfolio holdings including quantities, "
            "cost basis, market values, and unrealized gains/losses. "
            "Call this before answering any question about positions or portfolio composition."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of account IDs to filter. Omit for all accounts.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_portfolio_analytics",
        "description": (
            "Compute and return portfolio analytics including performance metrics "
            "(total return, TWR, Sharpe ratio) and risk metrics (volatility, max drawdown, beta). "
            "Use this when asked about performance, risk, or comparison to benchmarks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["1M", "3M", "6M", "YTD", "1Y", "3Y", "ALL"],
                    "description": "Time period for analytics. Default: 1Y.",
                },
                "benchmark": {
                    "type": "string",
                    "description": "Benchmark ticker symbol (e.g. SPY, QQQ, BTC). Default: SPY.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_current_prices",
        "description": "Fetch real-time or latest prices for a list of ticker symbols.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols (e.g. ['AAPL', 'BTC', 'ETH']).",
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_tax_summary",
        "description": (
            "Get tax information including realized gains/losses, "
            "estimated tax liability, and tax-loss harvesting opportunities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tax_year": {
                    "type": "integer",
                    "description": "Tax year (default: current year).",
                },
                "include_tlh_opportunities": {
                    "type": "boolean",
                    "description": "Whether to include tax-loss harvesting opportunities.",
                },
            },
            "required": [],
        },
    },
]

SYSTEM_PROMPT = """You are an expert investment intelligence assistant for a fintech platform.
You have access to tools that let you fetch real-time portfolio data, market prices, analytics, and tax information.

## Your capabilities:
- Analyze portfolio composition, concentration, and diversification
- Identify risks: sector overexposure, single-stock concentration, crypto volatility
- Interpret performance metrics (TWR, Sharpe, drawdown, beta)
- Suggest tax-loss harvesting opportunities
- Explain financial concepts clearly

## Behavior guidelines:
1. ALWAYS fetch relevant data before answering questions about the portfolio
2. Be specific and quantitative — use actual numbers from the data
3. Keep responses focused and actionable
4. Flag risks clearly but without causing panic
5. When you identify an issue, suggest a concrete action

## Important disclaimer:
Always end responses that include investment recommendations with:
"⚠️ This analysis is for informational purposes only and does not constitute financial advice.
Please consult a licensed financial advisor before making investment decisions."

User context: {user_name} | Total accounts: {account_count} | Base currency: {currency}
"""


@dataclass
class AdvisorResponse:
    content: str
    session_id: str
    tool_calls: list[str]
    input_tokens: int
    output_tokens: int


class AIAdvisorService:
    """
    Agentic AI advisor using Claude with tool use.
    Maintains conversation history per session.
    """

    def __init__(
        self,
        db: AsyncSession,
        portfolio_engine: PortfolioEngine,
        analytics_engine: AnalyticsEngine,
        market_data: MarketDataService,
        tax_engine: "TaxEngine",
    ):
        self.db = db
        self.portfolio_engine = portfolio_engine
        self.analytics_engine = analytics_engine
        self.market_data = market_data
        self.tax_engine = tax_engine
        self.client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )

    async def chat(
        self,
        user: User,
        message: str,
        session_id: Optional[str] = None,
    ) -> AdvisorResponse:
        """
        Send a message and get an AI response.
        Implements the Claude tool-use agentic loop.
        """
        # Load or create conversation
        conversation = await self._get_or_create_conversation(user, session_id)
        messages = list(conversation.messages)

        # Add user message
        messages.append({"role": "user", "content": message})

        system = SYSTEM_PROMPT.format(
            user_name=user.full_name or user.email,
            account_count=len(user.accounts) if hasattr(user, "accounts") else "unknown",
            currency=user.preferred_currency,
        )

        total_input_tokens = 0
        total_output_tokens = 0
        tool_calls_made: list[str] = []

        # Agentic loop
        max_iterations = 5
        for _ in range(max_iterations):
            response = await self.client.messages.create(
                model=settings.claude_model,
                max_tokens=settings.claude_max_tokens,
                system=system,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                # Final response
                text = self._extract_text(response.content)
                messages.append({"role": "assistant", "content": response.content})
                break

            elif response.stop_reason == "tool_use":
                # Execute tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_calls_made.append(block.name)
                        result = await self._execute_tool(block.name, block.input, user)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            else:
                text = self._extract_text(response.content)
                break
        else:
            text = "I've analyzed your portfolio. Please ask a more specific question for detailed insights."

        # Save conversation
        conversation.messages = messages
        conversation.total_input_tokens += total_input_tokens
        conversation.total_output_tokens += total_output_tokens
        conversation.last_active_at = datetime.now(timezone.utc)
        if not conversation.title and message:
            conversation.title = message[:60] + ("..." if len(message) > 60 else "")

        await self.db.commit()

        return AdvisorResponse(
            content=text,
            session_id=conversation.id,
            tool_calls=tool_calls_made,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    async def stream_chat(
        self,
        user: User,
        message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens via SSE."""
        # For streaming, we first do the full tool loop, then stream the final answer
        # In production, use streaming_extended_thinking or stream=True with tool callbacks

        response = await self.chat(user, message, session_id)

        # Simulate streaming by yielding chunks
        words = response.content.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")

    # ─── Tool Execution ──────────────────────────────────────────────────

    async def _execute_tool(self, name: str, inputs: dict, user: User) -> dict:
        """Dispatch tool calls to the appropriate service."""
        logger.info(f"AI advisor executing tool: {name} for user {user.id}")

        try:
            match name:
                case "get_portfolio_holdings":
                    return await self._tool_get_holdings(user, inputs)
                case "get_portfolio_analytics":
                    return await self._tool_get_analytics(user, inputs)
                case "get_current_prices":
                    return await self._tool_get_prices(inputs)
                case "get_tax_summary":
                    return await self._tool_get_tax(user, inputs)
                case _:
                    return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"error": str(e)}

    async def _tool_get_holdings(self, user: User, inputs: dict) -> dict:
        account_ids = inputs.get("account_ids")
        summary = await self.portfolio_engine.get_portfolio_summary(
            user_id=user.id,
            account_ids=account_ids,
            cost_basis_method=user.cost_basis_method,
        )
        return {
            "total_market_value_usd": float(summary.total_market_value),
            "total_cost_basis_usd": float(summary.total_cost_basis),
            "total_unrealized_gain_usd": float(summary.total_unrealized_gain),
            "total_unrealized_gain_pct": float(summary.total_unrealized_gain_pct),
            "dividend_income_usd": float(summary.dividend_income),
            "staking_income_usd": float(summary.staking_income),
            "holdings": [
                {
                    "symbol": h.symbol,
                    "name": h.name,
                    "asset_class": h.asset_class,
                    "quantity": float(h.quantity),
                    "average_cost_basis_usd": float(h.average_cost_basis) if h.average_cost_basis else None,
                    "market_value_usd": float(h.market_value) if h.market_value else None,
                    "weight_pct": round(float(h.market_value or 0) / float(summary.total_market_value) * 100, 2) if summary.total_market_value else 0,
                    "unrealized_gain_usd": float(h.unrealized_gain) if h.unrealized_gain else None,
                    "unrealized_gain_pct": float(h.unrealized_gain_pct) if h.unrealized_gain_pct else None,
                }
                for h in summary.holdings
            ],
        }

    async def _tool_get_analytics(self, user: User, inputs: dict) -> dict:
        period = inputs.get("period", "1Y")
        benchmark = inputs.get("benchmark", "SPY")

        bundle = await self.analytics_engine.compute_all(
            user_id=user.id,
            period=period,
            benchmark_symbol=benchmark,
            cost_basis_method=user.cost_basis_method,
        )
        return {
            "period": period,
            "benchmark": benchmark,
            "performance": {
                "total_return_pct": bundle.performance.total_return_pct,
                "annualized_return_pct": bundle.performance.annualized_return_pct,
                "twr_pct": bundle.performance.twr_pct,
                "benchmark_return_pct": bundle.performance.benchmark_return_pct,
                "alpha": bundle.performance.alpha,
                "beta": bundle.performance.beta,
            },
            "risk": {
                "volatility_annual_pct": bundle.risk.volatility_annual_pct,
                "sharpe_ratio": bundle.risk.sharpe_ratio,
                "sortino_ratio": bundle.risk.sortino_ratio,
                "max_drawdown_pct": bundle.risk.max_drawdown_pct,
                "var_95_pct": bundle.risk.var_95_pct,
                "beta_vs_benchmark": bundle.risk.beta_vs_benchmark,
            },
            "allocation": {
                "by_asset_class": bundle.allocation.by_asset_class,
                "top_holdings": bundle.allocation.top_holdings[:10],
                "concentration_score": bundle.allocation.concentration_score,
                "diversification_score": bundle.allocation.diversification_score,
            },
        }

    async def _tool_get_prices(self, inputs: dict) -> dict:
        symbols = inputs.get("symbols", [])
        prices = await self.market_data.get_batch_prices(symbols)
        return {"prices": {sym: round(price, 4) for sym, price in prices.items()}}

    async def _tool_get_tax(self, user: User, inputs: dict) -> dict:
        year = inputs.get("tax_year", datetime.now().year)
        include_tlh = inputs.get("include_tlh_opportunities", True)

        report = await self.tax_engine.compute_tax_summary(
            user_id=user.id,
            tax_year=year,
            include_tlh=include_tlh,
        )
        return {
            "tax_year": year,
            "realized_gains": {
                "short_term_gains_usd": float(report.short_term_gains),
                "long_term_gains_usd": float(report.long_term_gains),
                "total_gains_usd": float(report.total_gains),
            },
            "income": {
                "dividend_income_usd": float(report.dividend_income),
                "staking_income_usd": float(report.staking_income),
            },
            "tlh_opportunities": [
                {
                    "symbol": opp["symbol"],
                    "unrealized_loss_usd": opp["unrealized_loss"],
                    "tax_savings_estimate_usd": opp["tax_savings"],
                }
                for opp in (report.tlh_opportunities or [])
            ] if include_tlh else [],
        }

    # ─── Helpers ─────────────────────────────────────────────────────────

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

    @staticmethod
    def _extract_text(content: list) -> str:
        texts = []
        for block in content:
            if hasattr(block, "type") and block.type == "text":
                texts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)
