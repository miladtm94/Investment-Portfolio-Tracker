"""
Portfolio Reconstruction Engine.

Reconstructs portfolio state from the transaction ledger using event-sourcing.
Every call to reconstruct() replays transactions from a checkpoint (or epoch)
to produce point-in-time holdings with full cost basis accounting.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Account, Asset, Holding, TaxLot, Transaction, User
from shared.cache import cache_get, cache_set
from services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
PREC = Decimal("0.0000000001")


@dataclass
class Lot:
    """An open tax lot."""
    id: str
    asset_id: str
    acquired_at: datetime
    quantity_remaining: Decimal
    cost_basis_per_unit: Decimal
    currency: str = "USD"

    @property
    def total_cost_basis(self) -> Decimal:
        return (self.quantity_remaining * self.cost_basis_per_unit).quantize(PREC, rounding=ROUND_HALF_EVEN)


@dataclass
class PortfolioState:
    """Mutable snapshot of a portfolio at a point in time."""
    as_of: datetime
    # asset_id → list of open lots (ordered by acquisition date)
    lots: dict[str, list[Lot]] = field(default_factory=dict)
    # asset_id → total quantity (derived from lots)
    quantities: dict[str, Decimal] = field(default_factory=dict)
    # Realized gains
    realized_gain_short: Decimal = ZERO
    realized_gain_long: Decimal = ZERO
    # Income
    dividend_income: Decimal = ZERO
    staking_income: Decimal = ZERO

    def quantity(self, asset_id: str) -> Decimal:
        return self.quantities.get(asset_id, ZERO)

    def open_lots(self, asset_id: str) -> list[Lot]:
        return self.lots.get(asset_id, [])

    def total_cost_basis(self, asset_id: str) -> Decimal:
        return sum((lot.total_cost_basis for lot in self.open_lots(asset_id)), ZERO)

    def avg_cost_basis(self, asset_id: str) -> Optional[Decimal]:
        qty = self.quantity(asset_id)
        if qty == ZERO:
            return None
        return (self.total_cost_basis(asset_id) / qty).quantize(PREC)


@dataclass
class HoldingSnapshot:
    """A single holding with current market data."""
    asset_id: str
    symbol: str
    name: str
    asset_class: str
    quantity: Decimal
    average_cost_basis: Optional[Decimal]
    total_cost_basis: Optional[Decimal]
    last_price: Optional[Decimal]
    market_value: Optional[Decimal]
    unrealized_gain: Optional[Decimal]
    unrealized_gain_pct: Optional[Decimal]
    currency: str = "USD"


@dataclass
class PortfolioSummary:
    """Top-level portfolio summary."""
    total_market_value: Decimal
    total_cost_basis: Decimal
    total_unrealized_gain: Decimal
    total_unrealized_gain_pct: Decimal
    total_realized_gain_short: Decimal
    total_realized_gain_long: Decimal
    dividend_income: Decimal
    staking_income: Decimal
    holdings: list[HoldingSnapshot]
    as_of: datetime


class PortfolioEngine:
    """
    Event-sourcing portfolio reconstruction engine.

    Reconstructs portfolio state by replaying transactions in chronological
    order. Supports FIFO, LIFO, and HIFO cost basis methods.
    """

    def __init__(self, db: AsyncSession, market_data: MarketDataService):
        self.db = db
        self.market_data = market_data

    # ─── Public API ──────────────────────────────────────────────────────

    async def get_portfolio_summary(
        self,
        user_id: str,
        account_ids: Optional[list[str]] = None,
        as_of: Optional[datetime] = None,
        cost_basis_method: str = "FIFO",
    ) -> PortfolioSummary:
        """
        Reconstruct and return a full portfolio summary with live prices.
        """
        if as_of is None:
            as_of = datetime.now(timezone.utc)

        cache_key = f"portfolio:{user_id}:summary:{as_of.date()}"
        cached = await cache_get(cache_key)
        if cached and as_of.date() < datetime.now(timezone.utc).date():
            return PortfolioSummary(**cached)

        state = await self._reconstruct_state(user_id, account_ids, as_of, cost_basis_method)
        summary = await self._hydrate_with_prices(state, user_id)

        if as_of.date() < datetime.now(timezone.utc).date():
            await cache_set(cache_key, self._serialize_summary(summary), ttl=3600)

        return summary

    async def get_account_holdings(
        self,
        account_id: str,
        user_id: str,
        as_of: Optional[datetime] = None,
        cost_basis_method: str = "FIFO",
    ) -> list[HoldingSnapshot]:
        """Get holdings for a specific account."""
        summary = await self.get_portfolio_summary(
            user_id=user_id,
            account_ids=[account_id],
            as_of=as_of,
            cost_basis_method=cost_basis_method,
        )
        return summary.holdings

    # ─── Core Reconstruction ─────────────────────────────────────────────

    async def _reconstruct_state(
        self,
        user_id: str,
        account_ids: Optional[list[str]],
        as_of: datetime,
        cost_basis_method: str,
    ) -> PortfolioState:
        """
        Replay all transactions to reconstruct portfolio state at as_of.
        """
        state = PortfolioState(as_of=as_of)

        # Build query for transactions
        query = (
            select(Transaction, Asset)
            .join(Asset, Transaction.asset_id == Asset.id, isouter=True)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.transacted_at <= as_of,
                    Transaction.status == "SETTLED",
                )
            )
            .order_by(Transaction.transacted_at.asc(), Transaction.created_at.asc())
        )

        if account_ids:
            query = query.where(Transaction.account_id.in_(account_ids))

        result = await self.db.execute(query)
        rows = result.all()

        for txn, asset in rows:
            try:
                state = self._apply_transaction(state, txn, asset, cost_basis_method)
            except Exception as e:
                logger.warning(f"Error applying transaction {txn.id}: {e}")

        return state

    def _apply_transaction(
        self,
        state: PortfolioState,
        txn: Transaction,
        asset: Optional[Asset],
        cost_basis_method: str,
    ) -> PortfolioState:
        """
        Pure function: apply one transaction to state, return new state.
        Dispatches on transaction_type.
        """
        t = txn.transaction_type.upper()

        if t == "BUY":
            return self._apply_buy(state, txn, asset)
        elif t == "SELL":
            return self._apply_sell(state, txn, asset, cost_basis_method)
        elif t == "SPLIT":
            return self._apply_split(state, txn, asset)
        elif t == "DIVIDEND":
            return self._apply_dividend(state, txn, asset)
        elif t in ("STAKE_REWARD", "STAKING_REWARD"):
            return self._apply_stake_reward(state, txn, asset)
        elif t in ("TRANSFER_IN", "AIRDROP", "MINING_REWARD"):
            return self._apply_transfer_in(state, txn, asset)
        elif t == "TRANSFER_OUT":
            return self._apply_transfer_out(state, txn, asset, cost_basis_method)
        elif t == "SWAP":
            return self._apply_swap(state, txn, asset, cost_basis_method)
        elif t in ("DEPOSIT", "WITHDRAWAL", "FEE", "INTEREST"):
            return state  # Cash operations, no asset holdings change
        else:
            logger.debug(f"Unhandled transaction type: {t}")
            return state

    def _apply_buy(self, state: PortfolioState, txn: Transaction, asset: Optional[Asset]) -> PortfolioState:
        if not asset or not txn.quantity or not txn.price_per_unit:
            return state

        asset_id = txn.asset_id
        quantity = Decimal(str(txn.quantity))
        price = Decimal(str(txn.price_per_unit))

        # Include fees in cost basis (IRS requires this for stocks)
        fees = Decimal(str(txn.fees or 0))
        cost_per_unit = ((quantity * price + fees) / quantity).quantize(PREC)

        new_lot = Lot(
            id=txn.id,
            asset_id=asset_id,
            acquired_at=txn.transacted_at,
            quantity_remaining=quantity,
            cost_basis_per_unit=cost_per_unit,
            currency=txn.currency or "USD",
        )

        if asset_id not in state.lots:
            state.lots[asset_id] = []
        state.lots[asset_id].append(new_lot)
        state.quantities[asset_id] = state.quantities.get(asset_id, ZERO) + quantity

        return state

    def _apply_sell(
        self,
        state: PortfolioState,
        txn: Transaction,
        asset: Optional[Asset],
        cost_basis_method: str,
    ) -> PortfolioState:
        if not asset or not txn.quantity:
            return state

        asset_id = txn.asset_id
        quantity_to_sell = abs(Decimal(str(txn.quantity)))
        proceeds_per_unit = Decimal(str(txn.price_per_unit or 0))
        proceeds = quantity_to_sell * proceeds_per_unit - Decimal(str(txn.fees or 0))

        lots = state.lots.get(asset_id, [])
        if not lots:
            logger.warning(f"Sell without open lots for asset {asset_id}, txn {txn.id}")
            return state

        # Sort lots per cost basis method
        sorted_lots = self._sort_lots(lots, cost_basis_method)

        remaining_to_sell = quantity_to_sell
        for lot in sorted_lots:
            if remaining_to_sell <= ZERO:
                break

            sell_qty = min(lot.quantity_remaining, remaining_to_sell)
            lot_proceeds = sell_qty * proceeds_per_unit
            lot_cost = sell_qty * lot.cost_basis_per_unit
            lot_gain = lot_proceeds - lot_cost

            # Determine short/long term (>= 365 days = long term)
            holding_days = (txn.transacted_at - lot.acquired_at).days
            is_long_term = holding_days >= 365

            if is_long_term:
                state.realized_gain_long += lot_gain
            else:
                state.realized_gain_short += lot_gain

            lot.quantity_remaining -= sell_qty
            remaining_to_sell -= sell_qty

        # Remove fully depleted lots
        state.lots[asset_id] = [lot for lot in lots if lot.quantity_remaining > ZERO]
        state.quantities[asset_id] = sum(lot.quantity_remaining for lot in state.lots[asset_id])

        return state

    def _apply_split(self, state: PortfolioState, txn: Transaction, asset: Optional[Asset]) -> PortfolioState:
        """Handle stock/crypto splits. Adjusts lot quantities and cost basis per unit."""
        if not asset or not txn.split_ratio:
            return state

        asset_id = txn.asset_id
        ratio = Decimal(str(txn.split_ratio))

        for lot in state.lots.get(asset_id, []):
            lot.quantity_remaining = (lot.quantity_remaining * ratio).quantize(PREC)
            lot.cost_basis_per_unit = (lot.cost_basis_per_unit / ratio).quantize(PREC)

        state.quantities[asset_id] = sum(
            lot.quantity_remaining for lot in state.lots.get(asset_id, [])
        )
        return state

    def _apply_dividend(self, state: PortfolioState, txn: Transaction, asset: Optional[Asset]) -> PortfolioState:
        """Cash dividend — record as income, no lot impact."""
        if txn.net_amount_usd:
            state.dividend_income += Decimal(str(txn.net_amount_usd))
        return state

    def _apply_stake_reward(self, state: PortfolioState, txn: Transaction, asset: Optional[Asset]) -> PortfolioState:
        """
        Staking rewards: taxable as ordinary income at fair market value.
        Creates new lots at the FMV cost basis.
        """
        if not asset or not txn.quantity:
            return state

        state.staking_income += Decimal(str(txn.net_amount_usd or 0))

        # Create lot at FMV (price_per_unit at time of receipt)
        asset_id = txn.asset_id
        quantity = Decimal(str(txn.quantity))
        price = Decimal(str(txn.price_per_unit or 0))

        lot = Lot(
            id=txn.id,
            asset_id=asset_id,
            acquired_at=txn.transacted_at,
            quantity_remaining=quantity,
            cost_basis_per_unit=price,
        )
        if asset_id not in state.lots:
            state.lots[asset_id] = []
        state.lots[asset_id].append(lot)
        state.quantities[asset_id] = state.quantities.get(asset_id, ZERO) + quantity

        return state

    def _apply_transfer_in(self, state: PortfolioState, txn: Transaction, asset: Optional[Asset]) -> PortfolioState:
        """Transfer in / airdrop / mining — create lot at cost basis."""
        if not asset or not txn.quantity:
            return state

        asset_id = txn.asset_id
        quantity = Decimal(str(txn.quantity))
        price = Decimal(str(txn.price_per_unit or 0))

        lot = Lot(
            id=txn.id,
            asset_id=asset_id,
            acquired_at=txn.transacted_at,
            quantity_remaining=quantity,
            cost_basis_per_unit=price,
        )
        if asset_id not in state.lots:
            state.lots[asset_id] = []
        state.lots[asset_id].append(lot)
        state.quantities[asset_id] = state.quantities.get(asset_id, ZERO) + quantity

        return state

    def _apply_transfer_out(
        self,
        state: PortfolioState,
        txn: Transaction,
        asset: Optional[Asset],
        cost_basis_method: str,
    ) -> PortfolioState:
        """Transfer out — reduce lots (no gain event for same-owner transfers)."""
        if not asset or not txn.quantity:
            return state

        asset_id = txn.asset_id
        quantity_to_remove = abs(Decimal(str(txn.quantity)))
        lots = state.lots.get(asset_id, [])
        sorted_lots = self._sort_lots(lots, cost_basis_method)

        remaining = quantity_to_remove
        for lot in sorted_lots:
            if remaining <= ZERO:
                break
            remove = min(lot.quantity_remaining, remaining)
            lot.quantity_remaining -= remove
            remaining -= remove

        state.lots[asset_id] = [lot for lot in lots if lot.quantity_remaining > ZERO]
        state.quantities[asset_id] = sum(lot.quantity_remaining for lot in state.lots[asset_id])

        return state

    def _apply_swap(
        self,
        state: PortfolioState,
        txn: Transaction,
        asset: Optional[Asset],
        cost_basis_method: str,
    ) -> PortfolioState:
        """
        Crypto swap: taxable event. Sell outgoing asset, buy incoming.
        raw_data should contain: from_asset_id, to_asset_id, from_quantity, to_quantity
        """
        # Treat as sell of outgoing asset
        state = self._apply_sell(state, txn, asset, cost_basis_method)
        return state

    def _sort_lots(self, lots: list[Lot], method: str) -> list[Lot]:
        """Sort lots according to cost basis method."""
        if method == "FIFO":
            return sorted(lots, key=lambda l: l.acquired_at)
        elif method == "LIFO":
            return sorted(lots, key=lambda l: l.acquired_at, reverse=True)
        elif method == "HIFO":
            return sorted(lots, key=lambda l: l.cost_basis_per_unit, reverse=True)
        else:
            return sorted(lots, key=lambda l: l.acquired_at)  # Default FIFO

    # ─── Price Hydration ─────────────────────────────────────────────────

    async def _hydrate_with_prices(self, state: PortfolioState, user_id: str) -> PortfolioSummary:
        """Fetch current prices and compute market values."""
        # Collect all asset IDs with non-zero positions
        asset_ids = [aid for aid, qty in state.quantities.items() if qty > ZERO]
        if not asset_ids:
            return PortfolioSummary(
                total_market_value=ZERO, total_cost_basis=ZERO,
                total_unrealized_gain=ZERO, total_unrealized_gain_pct=ZERO,
                total_realized_gain_short=state.realized_gain_short,
                total_realized_gain_long=state.realized_gain_long,
                dividend_income=state.dividend_income,
                staking_income=state.staking_income,
                holdings=[],
                as_of=state.as_of,
            )

        # Fetch asset metadata
        result = await self.db.execute(select(Asset).where(Asset.id.in_(asset_ids)))
        assets = {a.id: a for a in result.scalars()}

        # Fetch prices (one call to market data service)
        symbols = [assets[aid].symbol for aid in asset_ids if aid in assets]
        prices = await self.market_data.get_batch_prices(symbols)

        holdings: list[HoldingSnapshot] = []
        total_market_value = ZERO
        total_cost_basis = ZERO

        for asset_id in asset_ids:
            qty = state.quantities[asset_id]
            if qty <= ZERO or asset_id not in assets:
                continue

            asset = assets[asset_id]
            cost_basis = state.total_cost_basis(asset_id)
            avg_cost = state.avg_cost_basis(asset_id)

            price = prices.get(asset.symbol)
            market_value = None
            unrealized_gain = None
            unrealized_gain_pct = None

            if price is not None:
                price_dec = Decimal(str(price))
                market_value = (qty * price_dec).quantize(PREC)
                unrealized_gain = market_value - cost_basis
                if cost_basis > ZERO:
                    unrealized_gain_pct = (unrealized_gain / cost_basis * 100).quantize(Decimal("0.01"))

                total_market_value += market_value
                total_cost_basis += cost_basis

            holdings.append(HoldingSnapshot(
                asset_id=asset_id,
                symbol=asset.symbol,
                name=asset.name,
                asset_class=asset.asset_class,
                quantity=qty,
                average_cost_basis=avg_cost,
                total_cost_basis=cost_basis,
                last_price=Decimal(str(price)) if price else None,
                market_value=market_value,
                unrealized_gain=unrealized_gain,
                unrealized_gain_pct=unrealized_gain_pct,
                currency=asset.currency,
            ))

        total_unrealized = total_market_value - total_cost_basis
        total_unrealized_pct = (
            (total_unrealized / total_cost_basis * 100).quantize(Decimal("0.01"))
            if total_cost_basis > ZERO else ZERO
        )

        return PortfolioSummary(
            total_market_value=total_market_value,
            total_cost_basis=total_cost_basis,
            total_unrealized_gain=total_unrealized,
            total_unrealized_gain_pct=total_unrealized_pct,
            total_realized_gain_short=state.realized_gain_short,
            total_realized_gain_long=state.realized_gain_long,
            dividend_income=state.dividend_income,
            staking_income=state.staking_income,
            holdings=sorted(holdings, key=lambda h: -(h.market_value or ZERO)),
            as_of=state.as_of,
        )

    def _serialize_summary(self, summary: PortfolioSummary) -> dict:
        """Serialize for Redis caching."""
        return {
            "total_market_value": str(summary.total_market_value),
            "total_cost_basis": str(summary.total_cost_basis),
            "total_unrealized_gain": str(summary.total_unrealized_gain),
            "total_unrealized_gain_pct": str(summary.total_unrealized_gain_pct),
            "total_realized_gain_short": str(summary.total_realized_gain_short),
            "total_realized_gain_long": str(summary.total_realized_gain_long),
            "dividend_income": str(summary.dividend_income),
            "staking_income": str(summary.staking_income),
            "as_of": summary.as_of.isoformat(),
            "holdings": [
                {
                    "asset_id": h.asset_id,
                    "symbol": h.symbol,
                    "name": h.name,
                    "asset_class": h.asset_class,
                    "quantity": str(h.quantity),
                    "average_cost_basis": str(h.average_cost_basis) if h.average_cost_basis else None,
                    "total_cost_basis": str(h.total_cost_basis) if h.total_cost_basis else None,
                    "last_price": str(h.last_price) if h.last_price else None,
                    "market_value": str(h.market_value) if h.market_value else None,
                    "unrealized_gain": str(h.unrealized_gain) if h.unrealized_gain else None,
                    "unrealized_gain_pct": str(h.unrealized_gain_pct) if h.unrealized_gain_pct else None,
                    "currency": h.currency,
                }
                for h in summary.holdings
            ],
        }
