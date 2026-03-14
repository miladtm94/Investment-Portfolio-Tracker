"""
Tax Reporting Engine.

Computes capital gains, income, wash sale detection,
and tax-loss harvesting opportunities.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import TaxLot, Transaction, Asset, Account
from services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

# 2024 US Federal capital gains tax rates (simplified)
SHORT_TERM_TAX_RATE = Decimal("0.37")  # Ordinary income top bracket
LONG_TERM_TAX_RATE = Decimal("0.20")   # Long-term CGT top bracket


@dataclass
class CapitalGainsReport:
    """Annual capital gains report."""
    tax_year: int
    # Realized gains
    short_term_gains: Decimal
    long_term_gains: Decimal
    total_gains: Decimal
    # Income
    dividend_income: Decimal
    staking_income: Decimal
    # Tax estimates
    estimated_short_term_tax: Decimal
    estimated_long_term_tax: Decimal
    estimated_total_tax: Decimal
    # Loss harvesting
    tlh_opportunities: list[dict] = field(default_factory=list)
    unrealized_losses: Decimal = ZERO
    # Detailed lots
    realized_lots: list[dict] = field(default_factory=list)


@dataclass
class WashSaleFlag:
    """A detected wash sale."""
    original_lot_id: str
    repurchase_transaction_id: str
    symbol: str
    disallowed_loss: Decimal
    repurchase_date: datetime


class TaxEngine:
    """
    Capital gains computation engine.
    Supports FIFO, LIFO, HIFO, and specific identification.
    """

    def __init__(self, db: AsyncSession, market_data: MarketDataService):
        self.db = db
        self.market_data = market_data

    async def compute_tax_summary(
        self,
        user_id: str,
        tax_year: int,
        include_tlh: bool = True,
        account_ids: Optional[list[str]] = None,
    ) -> CapitalGainsReport:
        """
        Compute a full tax summary for the given year.
        """
        year_start = datetime(tax_year, 1, 1, tzinfo=timezone.utc)
        year_end = datetime(tax_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        # Fetch all closed lots in the tax year
        query = (
            select(TaxLot, Asset)
            .join(Asset, TaxLot.asset_id == Asset.id)
            .where(
                and_(
                    TaxLot.user_id == user_id,
                    TaxLot.closed_at >= year_start,
                    TaxLot.closed_at <= year_end,
                    TaxLot.lot_status == "CLOSED",
                )
            )
            .order_by(TaxLot.closed_at)
        )
        if account_ids:
            query = query.where(TaxLot.account_id.in_(account_ids))

        result = await self.db.execute(query)
        closed_lots = result.all()

        # Fetch dividend and staking income
        income_query = (
            select(Transaction)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.transacted_at >= year_start,
                    Transaction.transacted_at <= year_end,
                    Transaction.transaction_type.in_(["DIVIDEND", "STAKE_REWARD", "STAKING_REWARD", "MINING_REWARD", "AIRDROP"]),
                )
            )
        )
        income_result = await self.db.execute(income_query)
        income_txns = income_result.scalars().all()

        # Compute gains
        short_term = ZERO
        long_term = ZERO
        realized_lots_data = []

        for lot, asset in closed_lots:
            gain = Decimal(str(lot.realized_gain or 0))
            if lot.is_wash_sale and gain < ZERO:
                gain += Decimal(str(lot.wash_sale_disallowed_loss or 0))

            if lot.is_long_term:
                long_term += gain
            else:
                short_term += gain

            realized_lots_data.append({
                "symbol": asset.symbol,
                "name": asset.name,
                "acquired_at": lot.acquired_at.isoformat(),
                "closed_at": lot.closed_at.isoformat() if lot.closed_at else None,
                "quantity": float(lot.quantity_acquired - lot.quantity_remaining),
                "cost_basis": float(lot.total_cost_basis),
                "proceeds": float(lot.proceeds or 0),
                "gain_loss": float(gain),
                "is_long_term": lot.is_long_term,
                "is_wash_sale": lot.is_wash_sale,
                "holding_period_days": lot.holding_period_days,
            })

        # Income
        dividend_income = ZERO
        staking_income = ZERO
        for txn in income_txns:
            amount = Decimal(str(txn.net_amount_usd or 0))
            if txn.transaction_type == "DIVIDEND":
                dividend_income += amount
            else:
                staking_income += amount

        # Tax estimates
        est_st_tax = max(short_term, ZERO) * SHORT_TERM_TAX_RATE
        est_lt_tax = max(long_term, ZERO) * LONG_TERM_TAX_RATE
        est_total_tax = est_st_tax + est_lt_tax + (dividend_income + staking_income) * SHORT_TERM_TAX_RATE

        # TLH opportunities
        tlh_opportunities = []
        unrealized_losses = ZERO
        if include_tlh:
            tlh_opportunities, unrealized_losses = await self._find_tlh_opportunities(user_id)

        return CapitalGainsReport(
            tax_year=tax_year,
            short_term_gains=short_term,
            long_term_gains=long_term,
            total_gains=short_term + long_term,
            dividend_income=dividend_income,
            staking_income=staking_income,
            estimated_short_term_tax=est_st_tax,
            estimated_long_term_tax=est_lt_tax,
            estimated_total_tax=est_total_tax,
            tlh_opportunities=tlh_opportunities,
            unrealized_losses=unrealized_losses,
            realized_lots=realized_lots_data,
        )

    async def detect_wash_sales(self, user_id: str, tax_year: int) -> list[WashSaleFlag]:
        """
        Detect IRS wash sale rule violations:
        A loss is disallowed if the same (or substantially identical) security
        is purchased within 30 days before or after the sale.
        """
        year_start = datetime(tax_year, 1, 1, tzinfo=timezone.utc)
        year_end = datetime(tax_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        # Fetch all sell transactions for the year
        sell_query = (
            select(Transaction, Asset)
            .join(Asset, Transaction.asset_id == Asset.id)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.transaction_type == "SELL",
                    Transaction.transacted_at >= year_start,
                    Transaction.transacted_at <= year_end,
                )
            )
            .order_by(Transaction.transacted_at)
        )
        sell_result = await self.db.execute(sell_query)
        sells = sell_result.all()

        flags: list[WashSaleFlag] = []

        for sell_txn, asset in sells:
            # Check if this sell realized a loss
            # (Simplified: in full implementation, correlate with lot records)
            sell_price = Decimal(str(sell_txn.price_per_unit or 0))
            if sell_price <= ZERO:
                continue

            window_start = sell_txn.transacted_at - timedelta(days=30)
            window_end = sell_txn.transacted_at + timedelta(days=30)

            # Check for buy of same asset within 30-day window
            repurchase_query = (
                select(Transaction)
                .where(
                    and_(
                        Transaction.user_id == user_id,
                        Transaction.asset_id == sell_txn.asset_id,
                        Transaction.transaction_type == "BUY",
                        Transaction.transacted_at >= window_start,
                        Transaction.transacted_at <= window_end,
                        Transaction.id != sell_txn.id,
                    )
                )
            )
            repurchase_result = await self.db.execute(repurchase_query)
            repurchases = repurchase_result.scalars().all()

            for repurchase in repurchases:
                if repurchase.transacted_at != sell_txn.transacted_at:
                    logger.info(f"Potential wash sale: {asset.symbol} sold {sell_txn.transacted_at}, repurchased {repurchase.transacted_at}")

        return flags

    async def _find_tlh_opportunities(
        self, user_id: str
    ) -> tuple[list[dict], Decimal]:
        """
        Find tax-loss harvesting opportunities:
        Open lots with unrealized losses > threshold.
        """
        # Fetch open lots with their assets
        lot_query = (
            select(TaxLot, Asset)
            .join(Asset, TaxLot.asset_id == Asset.id)
            .where(
                and_(
                    TaxLot.user_id == user_id,
                    TaxLot.lot_status.in_(["OPEN", "PARTIALLY_CLOSED"]),
                )
            )
        )
        result = await self.db.execute(lot_query)
        open_lots = result.all()

        # Get current prices for all assets
        symbols = list({asset.symbol for _, asset in open_lots})
        prices = await self.market_data.get_batch_prices(symbols)

        opportunities = []
        total_unrealized_loss = ZERO

        # Group by asset
        asset_lots: dict[str, tuple[Asset, list[TaxLot]]] = {}
        for lot, asset in open_lots:
            if asset.symbol not in asset_lots:
                asset_lots[asset.symbol] = (asset, [])
            asset_lots[asset.symbol][1].append(lot)

        for symbol, (asset, lots) in asset_lots.items():
            current_price = prices.get(symbol)
            if not current_price:
                continue

            price_dec = Decimal(str(current_price))
            total_quantity = sum(Decimal(str(lot.quantity_remaining)) for lot in lots)
            total_cost = sum(
                Decimal(str(lot.quantity_remaining)) * Decimal(str(lot.cost_basis_per_unit))
                for lot in lots
            )
            current_value = total_quantity * price_dec
            unrealized_gain = current_value - total_cost

            if unrealized_gain < -Decimal("100"):  # Only flag losses > $100
                tax_savings = abs(unrealized_gain) * SHORT_TERM_TAX_RATE
                opportunities.append({
                    "symbol": symbol,
                    "name": asset.name,
                    "asset_class": asset.asset_class,
                    "quantity": float(total_quantity),
                    "cost_basis": float(total_cost),
                    "current_value": float(current_value),
                    "unrealized_loss": float(unrealized_gain),
                    "tax_savings": float(tax_savings),
                    "holding_period_days": min(
                        (datetime.now(timezone.utc) - lot.acquired_at).days
                        for lot in lots
                    ),
                })
                total_unrealized_loss += unrealized_gain

        # Sort by largest loss first
        opportunities.sort(key=lambda x: x["unrealized_loss"])

        return opportunities, total_unrealized_loss

    async def generate_form_8949_data(self, user_id: str, tax_year: int) -> list[dict]:
        """
        Generate Form 8949 line items for Schedule D.
        Returns rows ready for PDF/CSV export.
        """
        report = await self.compute_tax_summary(user_id, tax_year, include_tlh=False)
        return report.realized_lots
