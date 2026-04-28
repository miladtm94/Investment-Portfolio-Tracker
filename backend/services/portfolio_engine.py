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
from services.fx_service import FXService

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
PREC = Decimal("0.0000000001")


def _norm_ccy(code: Optional[str]) -> str:
    return FXService._normalize_currency(code or "USD")


@dataclass
class Lot:
    """An open tax lot."""
    id: str
    asset_id: str
    acquired_at: datetime
    quantity_remaining: Decimal
    cost_basis_per_unit: Decimal
    currency: str = "USD"
    fx_rate_to_aud: Optional[Decimal] = None

    @property
    def total_cost_basis(self) -> Decimal:
        return (self.quantity_remaining * self.cost_basis_per_unit).quantize(PREC, rounding=ROUND_HALF_EVEN)


@dataclass
class FxEvent:
    """A dated cashflow or gain in original currency."""
    occurred_at: datetime
    currency: str
    amount: Decimal
    kind: str  # dividend|staking|realized_short|realized_long


@dataclass
class RealizedFxEvent:
    """A realized gain event with proceeds and cost converted independently."""
    occurred_at: datetime
    proceeds: Decimal
    proceeds_currency: str
    proceeds_fx_rate_to_aud: Optional[Decimal]
    cost_basis: Decimal
    cost_currency: str
    cost_acquired_at: datetime
    cost_fx_rate_to_aud: Optional[Decimal]
    kind: str  # realized_short|realized_long


@dataclass
class PortfolioState:
    """Mutable snapshot of a portfolio at a point in time."""
    as_of: datetime
    # asset_id → list of open lots (ordered by acquisition date)
    lots: dict[str, list[Lot]] = field(default_factory=dict)
    # asset_id → total quantity (derived from lots)
    quantities: dict[str, Decimal] = field(default_factory=dict)
    # Realized gains (in original currencies — converted at display time)
    realized_gain_short: Decimal = ZERO
    realized_gain_long: Decimal = ZERO
    realized_gains_by_currency: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    # Income
    dividend_income: Decimal = ZERO
    staking_income: Decimal = ZERO
    income_by_currency: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    fx_events: list[FxEvent] = field(default_factory=list)
    realized_fx_events: list[RealizedFxEvent] = field(default_factory=list)

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
    currency: str = "AUD"
    original_currency: str = "AUD"  # Quote currency used for current market prices


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
        display_currency: str = "AUD",
    ) -> PortfolioSummary:
        """
        Reconstruct and return a full portfolio summary with live prices.
        """
        if as_of is None:
            as_of = datetime.now(timezone.utc)

        # Include account_ids in cache key so different account combos don't collide
        acc_hash = hashlib.md5(",".join(sorted(account_ids or [])).encode()).hexdigest()[:8] if account_ids else "all"
        display_ccy = _norm_ccy(display_currency)
        cache_key = f"portfolio:{user_id}:summary:{as_of.date()}:{acc_hash}:{display_ccy}"
        cached = await cache_get(cache_key)
        if cached and as_of.date() < datetime.now(timezone.utc).date():
            return PortfolioSummary(**cached)

        state = await self._reconstruct_state(user_id, account_ids, as_of, cost_basis_method)
        summary = await self._hydrate_with_prices(state, user_id, display_ccy)

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
        elif t in ("DIVIDEND", "DISTRIBUTION"):
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
        ccy = _norm_ccy(txn.currency)
        price = Decimal(str(txn.price_per_unit))
        fees = abs(Decimal(str(txn.fees or 0)))
        cost_per_unit = ((quantity * price + fees) / quantity).quantize(PREC)

        new_lot = Lot(
            id=txn.id,
            asset_id=asset_id,
            acquired_at=txn.transacted_at,
            quantity_remaining=quantity,
            cost_basis_per_unit=cost_per_unit,
            currency=ccy,
            fx_rate_to_aud=Decimal(str(txn.fx_rate_to_aud)) if txn.fx_rate_to_aud else (Decimal("1.0") if ccy == "AUD" else None),
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

        ccy = _norm_ccy(txn.currency)
        proceeds_per_unit = Decimal(str(txn.price_per_unit or 0))
        fees = abs(Decimal(str(txn.fees or 0)))
        txn_fx_rate_to_aud = (
            Decimal(str(txn.fx_rate_to_aud))
            if txn.fx_rate_to_aud else (Decimal("1.0") if ccy == "AUD" else None)
        )

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
            fee_share = fees * (sell_qty / quantity_to_sell) if quantity_to_sell else ZERO
            lot_proceeds = (sell_qty * proceeds_per_unit) - fee_share
            lot_cost = sell_qty * lot.cost_basis_per_unit
            lot_gain = lot_proceeds - lot_cost

            # Determine short/long term (>= 365 days = long term)
            holding_days = (txn.transacted_at - lot.acquired_at).days
            is_long_term = holding_days >= 365

            kind = "realized_long" if is_long_term else "realized_short"
            if is_long_term:
                state.realized_gain_long += lot_gain
            else:
                state.realized_gain_short += lot_gain
            state.realized_fx_events.append(RealizedFxEvent(
                occurred_at=txn.transacted_at,
                proceeds=lot_proceeds,
                proceeds_currency=ccy,
                proceeds_fx_rate_to_aud=txn_fx_rate_to_aud,
                cost_basis=lot_cost,
                cost_currency=_norm_ccy(lot.currency),
                cost_acquired_at=lot.acquired_at,
                cost_fx_rate_to_aud=lot.fx_rate_to_aud,
                kind=kind,
            ))

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
        """Cash dividend — record as income in original currency, no lot impact."""
        amount = ZERO
        if txn.net_amount:
            amount = abs(Decimal(str(txn.net_amount)))
        elif txn.net_amount_usd:
            amount = Decimal(str(txn.net_amount_usd))

        ccy = _norm_ccy(txn.currency)
        if ccy not in state.income_by_currency:
            state.income_by_currency[ccy] = {"dividend": ZERO, "staking": ZERO}
        state.income_by_currency[ccy]["dividend"] += amount
        state.dividend_income += amount  # kept for backwards compat (will be overridden)
        state.fx_events.append(FxEvent(txn.transacted_at, ccy, amount, "dividend"))
        return state

    def _apply_stake_reward(self, state: PortfolioState, txn: Transaction, asset: Optional[Asset]) -> PortfolioState:
        """
        Staking rewards: taxable as ordinary income at fair market value.
        Creates new lots at the FMV cost basis.
        """
        if not asset or not txn.quantity:
            return state

        amount = Decimal(str(txn.net_amount or txn.net_amount_usd or 0))
        ccy = _norm_ccy(txn.currency)
        if ccy not in state.income_by_currency:
            state.income_by_currency[ccy] = {"dividend": ZERO, "staking": ZERO}
        state.income_by_currency[ccy]["staking"] += amount
        state.staking_income += amount
        state.fx_events.append(FxEvent(txn.transacted_at, ccy, amount, "staking"))

        # Create lot at FMV — keep original currency
        asset_id = txn.asset_id
        quantity = Decimal(str(txn.quantity))
        price = Decimal(str(txn.price_per_unit or 0))

        lot = Lot(
            id=txn.id,
            asset_id=asset_id,
            acquired_at=txn.transacted_at,
            quantity_remaining=quantity,
            cost_basis_per_unit=price,
            currency=ccy,
            fx_rate_to_aud=Decimal(str(txn.fx_rate_to_aud)) if txn.fx_rate_to_aud else (Decimal("1.0") if ccy == "AUD" else None),
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
        ccy = _norm_ccy(txn.currency)
        price = Decimal(str(txn.price_per_unit or 0))

        lot = Lot(
            id=txn.id,
            asset_id=asset_id,
            acquired_at=txn.transacted_at,
            quantity_remaining=quantity,
            cost_basis_per_unit=price,
            currency=ccy,
            fx_rate_to_aud=Decimal(str(txn.fx_rate_to_aud)) if txn.fx_rate_to_aud else (Decimal("1.0") if ccy == "AUD" else None),
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

    @staticmethod
    def _asset_price_currency(asset: Asset) -> str:
        """Currency returned by MarketDataService for this asset's prices."""
        if asset.asset_class.upper() == "CRYPTO":
            # CoinGecko calls in MarketDataService currently request USD quotes.
            return "USD"
        return _norm_ccy(asset.currency or "USD")

    async def _hydrate_with_prices(self, state: PortfolioState, user_id: str, display_currency: str) -> PortfolioSummary:
        """Fetch current prices and compute market values.

        Cost basis is kept per-lot in each transaction's currency.
        Market prices are fetched in the asset's quote currency.
        Everything is then converted to display currency for the summary using FX rates.
        """
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

        # Fetch prices — pass currency so ASX stocks use .AX suffix
        symbols = [assets[aid].symbol for aid in asset_ids if aid in assets]
        symbol_currencies = {
            assets[aid].symbol: self._asset_price_currency(assets[aid])
            for aid in asset_ids if aid in assets
        }
        prices = await self.market_data.get_batch_prices(symbols, symbol_currencies)

        target_ccy = _norm_ccy(display_currency)

        # Current FX rates for market prices → display currency
        spot_currencies = {
            self._asset_price_currency(assets[aid])
            for aid in asset_ids
            if aid in assets and self._asset_price_currency(assets[aid]) != target_ccy
        }

        fx = None
        spot_rates: dict[str, Decimal] = {}  # 1 foreign = X target_ccy
        if spot_currencies:
            fx = FXService()
            for ccy in spot_currencies:
                spot_rates[ccy] = await fx.get_rate_on_date(ccy, target_ccy, state.as_of)

        # Historical FX rates for cost basis + cashflows
        fx_rate_cache: dict[tuple[str, str, str], Decimal] = {}
        fx_requests: set[tuple[str, str, str]] = set()

        for asset_id in asset_ids:
            for lot in state.open_lots(asset_id):
                from_ccy = _norm_ccy(lot.currency)
                if from_ccy == target_ccy:
                    continue
                if target_ccy == "AUD" and lot.fx_rate_to_aud:
                    continue
                day = lot.acquired_at.date().isoformat()
                fx_requests.add((from_ccy, target_ccy, day))

        for ev in state.fx_events:
            from_ccy = _norm_ccy(ev.currency)
            if from_ccy == target_ccy:
                continue
            day = ev.occurred_at.date().isoformat()
            fx_requests.add((from_ccy, target_ccy, day))

        for ev in state.realized_fx_events:
            proceeds_ccy = _norm_ccy(ev.proceeds_currency)
            if proceeds_ccy != target_ccy and not (target_ccy == "AUD" and ev.proceeds_fx_rate_to_aud):
                fx_requests.add((proceeds_ccy, target_ccy, ev.occurred_at.date().isoformat()))
            cost_ccy = _norm_ccy(ev.cost_currency)
            if cost_ccy != target_ccy and not (target_ccy == "AUD" and ev.cost_fx_rate_to_aud):
                fx_requests.add((cost_ccy, target_ccy, ev.cost_acquired_at.date().isoformat()))

        if fx_requests and not fx:
            fx = FXService()

        if fx_requests:
            for from_c, to_c, day in fx_requests:
                dt = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
                fx_rate_cache[(from_c, to_c, day)] = await fx.get_rate_on_date(from_c, to_c, dt)

        if fx:
            await fx.close()

        def lot_to_display(cost_per_unit: Decimal, lot: Lot) -> Decimal:
            from_ccy = _norm_ccy(lot.currency)
            if from_ccy == target_ccy:
                return cost_per_unit
            if target_ccy == "AUD" and lot.fx_rate_to_aud:
                return (cost_per_unit * lot.fx_rate_to_aud).quantize(PREC)
            key = (from_ccy, target_ccy, lot.acquired_at.date().isoformat())
            rate = fx_rate_cache.get(key, Decimal("1"))
            return (cost_per_unit * rate).quantize(PREC)

        def spot_to_display(amount: Decimal, ccy: str) -> Decimal:
            from_ccy = _norm_ccy(ccy)
            if from_ccy == target_ccy:
                return amount
            rate = spot_rates.get(from_ccy, Decimal("1"))
            return (amount * rate).quantize(PREC)

        def amount_to_display(
            amount: Decimal,
            from_ccy: str,
            occurred_at: datetime,
            fx_rate_to_aud: Optional[Decimal] = None,
        ) -> Decimal:
            source_ccy = _norm_ccy(from_ccy)
            if source_ccy == target_ccy:
                return amount
            if target_ccy == "AUD" and fx_rate_to_aud:
                return (amount * fx_rate_to_aud).quantize(PREC)
            key = (source_ccy, target_ccy, occurred_at.date().isoformat())
            rate = fx_rate_cache.get(key, Decimal("1"))
            return (amount * rate).quantize(PREC)

        holdings: list[HoldingSnapshot] = []
        total_market_value = ZERO
        total_cost_basis = ZERO

        for asset_id in asset_ids:
            qty = state.quantities[asset_id]
            if qty <= ZERO or asset_id not in assets:
                continue

            asset = assets[asset_id]
            asset_ccy = self._asset_price_currency(asset)

            # Cost basis — convert each lot using historical FX for display currency
            cost_basis_display = ZERO
            for lot in state.open_lots(asset_id):
                cost_basis_display += (lot.quantity_remaining * lot_to_display(lot.cost_basis_per_unit, lot)).quantize(PREC)
            avg_cost_display = (cost_basis_display / qty).quantize(PREC) if qty > ZERO else None

            price = prices.get(asset.symbol)
            market_value_display = None
            unrealized_gain = None
            unrealized_gain_pct = None
            price_display = None

            if price is not None:
                price_dec = Decimal(str(price))
                # Market price in asset's trading currency → convert to display currency with current rate
                price_display = spot_to_display(price_dec, asset_ccy).quantize(Decimal("0.000001"))
                market_value_display = (qty * price_display).quantize(PREC)
                unrealized_gain = market_value_display - cost_basis_display
                if cost_basis_display > ZERO:
                    unrealized_gain_pct = (unrealized_gain / cost_basis_display * 100).quantize(Decimal("0.01"))

                total_market_value += market_value_display
                total_cost_basis += cost_basis_display

            holdings.append(HoldingSnapshot(
                asset_id=asset_id,
                symbol=asset.symbol,
                name=asset.name,
                asset_class=asset.asset_class,
                quantity=qty,
                average_cost_basis=avg_cost_display,
                total_cost_basis=cost_basis_display,
                last_price=price_display,
                market_value=market_value_display,
                unrealized_gain=unrealized_gain,
                unrealized_gain_pct=unrealized_gain_pct,
                currency=target_ccy,
                original_currency=asset_ccy,
            ))

        total_unrealized = total_market_value - total_cost_basis
        total_unrealized_pct = (
            (total_unrealized / total_cost_basis * 100).quantize(Decimal("0.01"))
            if total_cost_basis > ZERO else ZERO
        )

        # Convert income + realized gains to display currency using historical FX
        dividend_aud = ZERO
        staking_aud = ZERO
        realized_short = ZERO
        realized_long = ZERO
        if state.fx_events or state.realized_fx_events:
            for ev in state.fx_events:
                from_ccy = _norm_ccy(ev.currency)
                if from_ccy == target_ccy:
                    converted = ev.amount
                else:
                    key = (from_ccy, target_ccy, ev.occurred_at.date().isoformat())
                    rate = fx_rate_cache.get(key, Decimal("1"))
                    converted = (ev.amount * rate).quantize(PREC)
                if ev.kind == "dividend":
                    dividend_aud += converted
                elif ev.kind == "staking":
                    staking_aud += converted

            for ev in state.realized_fx_events:
                proceeds = amount_to_display(
                    ev.proceeds,
                    ev.proceeds_currency,
                    ev.occurred_at,
                    ev.proceeds_fx_rate_to_aud,
                )
                cost = amount_to_display(
                    ev.cost_basis,
                    ev.cost_currency,
                    ev.cost_acquired_at,
                    ev.cost_fx_rate_to_aud,
                )
                gain = proceeds - cost
                if ev.kind == "realized_short":
                    realized_short += gain
                elif ev.kind == "realized_long":
                    realized_long += gain
        else:
            # Fallback for older data
            dividend_aud = state.dividend_income
            staking_aud = state.staking_income
            realized_short = state.realized_gain_short
            realized_long = state.realized_gain_long

        return PortfolioSummary(
            total_market_value=total_market_value,
            total_cost_basis=total_cost_basis,
            total_unrealized_gain=total_unrealized,
            total_unrealized_gain_pct=total_unrealized_pct,
            total_realized_gain_short=realized_short,
            total_realized_gain_long=realized_long,
            dividend_income=dividend_aud,
            staking_income=staking_aud,
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
                    "average_cost_basis": str(h.average_cost_basis) if h.average_cost_basis is not None else None,
                    "total_cost_basis": str(h.total_cost_basis) if h.total_cost_basis is not None else None,
                    "last_price": str(h.last_price) if h.last_price is not None else None,
                    "market_value": str(h.market_value) if h.market_value is not None else None,
                    "unrealized_gain": str(h.unrealized_gain) if h.unrealized_gain is not None else None,
                    "unrealized_gain_pct": str(h.unrealized_gain_pct) if h.unrealized_gain_pct is not None else None,
                    "currency": h.currency,
                    "original_currency": h.original_currency,
                }
                for h in summary.holdings
            ],
        }
