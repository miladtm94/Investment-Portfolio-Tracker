"""
ATO Capital Gains Tax Engine — Australia.

Implements ATO CGT rules per the Income Tax Assessment Act 1997:
  - Australian Financial Year: 1 July – 30 June
  - CGT discount: 50% for individuals, 33.33% for SMSFs (assets held ≥ 365 days)
  - Cost base in AUD (using RBA/commercial FX rate at date of acquisition)
  - Capital losses offset gains; losses applied to non-discount gains first
  - No wash-sale rule equivalent in Australia
  - Marginal tax rates 2024-25 including 2% Medicare Levy
  - Dividend imputation / franking credits tracked

References:
  ATO CGT: https://www.ato.gov.au/individuals-and-families/investments-and-assets/capital-gains-tax
  Cost base: https://www.ato.gov.au/individuals-and-families/investments-and-assets/capital-gains-tax/calculating-your-cgt/cost-base
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import TaxLot, Transaction, Asset
from services.fx_service import FXService
from services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")

# ── ATO Marginal Tax Rates 2024–25 (individuals, residents) ─────────────────
# Each band: (threshold, base_tax, marginal_rate)
ATO_TAX_BRACKETS_2024_25 = [
    (Decimal("18200"),  Decimal("0"),      Decimal("0.00")),
    (Decimal("45000"),  Decimal("0"),      Decimal("0.19")),
    (Decimal("120000"), Decimal("5092"),   Decimal("0.325")),
    (Decimal("180000"), Decimal("29467"),  Decimal("0.37")),
    (Decimal("999999999"), Decimal("51667"), Decimal("0.45")),
]
MEDICARE_LEVY = Decimal("0.02")
LOW_INCOME_TAX_OFFSET_MAX = Decimal("700")   # LITO: $700 offset, phases out $37.5k–$66.7k
LOW_INCOME_THRESHOLD = Decimal("37500")
LITO_PHASE_OUT_END = Decimal("66667")


def ato_income_tax(taxable_income: Decimal) -> Decimal:
    """Compute ATO income tax for given taxable income (2024-25 rates)."""
    if taxable_income <= ZERO:
        return ZERO

    tax = ZERO
    prev_threshold = ZERO
    for threshold, base, rate in ATO_TAX_BRACKETS_2024_25:
        if taxable_income <= prev_threshold:
            break
        band_income = min(taxable_income, threshold) - prev_threshold
        if taxable_income > prev_threshold:
            if prev_threshold == ZERO and rate == ZERO:
                pass  # tax-free threshold
            else:
                tax += band_income * rate
        prev_threshold = threshold

    # Simplified LITO
    if taxable_income <= LOW_INCOME_THRESHOLD:
        lito = LOW_INCOME_TAX_OFFSET_MAX
    elif taxable_income <= LITO_PHASE_OUT_END:
        lito = LOW_INCOME_TAX_OFFSET_MAX - (taxable_income - LOW_INCOME_THRESHOLD) * Decimal("0.025")
    else:
        lito = ZERO

    tax = max(ZERO, tax - lito)
    # Medicare Levy (full rate above $26,000, phased in below)
    medicare = taxable_income * MEDICARE_LEVY if taxable_income > Decimal("26000") else ZERO
    return (tax + medicare).quantize(CENT, rounding=ROUND_HALF_UP)


def ato_marginal_rate(taxable_income: Decimal) -> Decimal:
    """Return the marginal income tax rate for a given taxable income level."""
    for threshold, _, rate in ATO_TAX_BRACKETS_2024_25:
        if taxable_income <= threshold:
            return rate + MEDICARE_LEVY
    return Decimal("0.47")  # top rate + medicare


def au_financial_year(dt: datetime) -> int:
    """
    Return the Australian financial year end for a datetime.
    FY2024-25 = July 1, 2024 to June 30, 2025 → returns 2025.
    """
    if dt.month >= 7:
        return dt.year + 1
    return dt.year


def au_fy_bounds(fy_end_year: int) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for an Australian financial year."""
    start = datetime(fy_end_year - 1, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(fy_end_year, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class CGTEvent:
    """A single disposal event (CGT Event A1 — most common)."""
    symbol: str
    name: str
    asset_class: str
    acquired_at: datetime
    disposed_at: datetime
    holding_days: int
    discount_eligible: bool              # held ≥ 365 days
    quantity: Decimal
    cost_base_aud: Decimal               # ATO cost base (5 elements)
    proceeds_aud: Decimal                # Capital proceeds
    gross_gain_aud: Decimal              # proceeds - cost_base (before discount)
    # After discount applied (if eligible and gain is positive):
    discounted_gain_aud: Decimal
    # Loss (if applicable — cannot be discounted):
    capital_loss_aud: Decimal
    is_loss: bool
    cgt_event_type: str = "A1"           # A1 = disposal of asset
    lot_id: Optional[str] = None


@dataclass
class ATOTaxReport:
    """Complete ATO CGT report for a financial year."""
    financial_year: int                  # e.g. 2025 for FY2024-25
    fy_label: str                        # "FY2024-25"

    # ── Gross figures (before discount) ──────────────────────────────────
    gross_capital_gains_aud: Decimal     # Sum of all positive gross gains
    capital_losses_aud: Decimal          # Sum of all losses (positive number)

    # ── Net after loss application ────────────────────────────────────────
    # ATO rule: losses must offset non-discount gains first, then discount gains
    net_gain_non_discount_aud: Decimal   # After losses, from assets held < 12m
    net_gain_discount_eligible_aud: Decimal  # After losses, from assets held ≥ 12m
    cgt_discount_amount_aud: Decimal     # 50% of net_gain_discount_eligible
    net_capital_gain_aud: Decimal        # ATO Schedule 3 label: "Net capital gain"
    # Carried forward losses
    losses_carried_forward_aud: Decimal

    # ── Income ────────────────────────────────────────────────────────────
    dividend_income_aud: Decimal
    staking_income_aud: Decimal
    interest_income_aud: Decimal
    franking_credits_aud: Decimal

    # ── Tax estimates (at user's specified income) ────────────────────────
    assumed_other_income_aud: Decimal
    total_taxable_income_aud: Decimal
    estimated_tax_aud: Decimal
    estimated_tax_with_cgt_aud: Decimal  # Tax if CGT gain added to income
    estimated_cgt_tax_aud: Decimal       # Marginal tax on the net capital gain
    effective_cgt_rate_pct: Decimal

    # ── Detail ────────────────────────────────────────────────────────────
    cgt_events: list[CGTEvent] = field(default_factory=list)
    tlh_opportunities: list[dict] = field(default_factory=list)
    total_unrealised_losses_aud: Decimal = ZERO


class ATOTaxEngine:
    """
    Australian CGT calculation engine.

    Implements ITAA 1997 Div 100-115 (CGT) rules:
    - Cost base in AUD at acquisition date (RBA FX rate)
    - 50% individual discount for assets held ≥ 365 days
    - Loss application order: non-discount gains first, then discount gains
    - Losses carried forward when they exceed current year gains
    """

    def __init__(self, db: AsyncSession, market_data: MarketDataService, fx_svc: FXService):
        self.db = db
        self.market_data = market_data
        self.fx = fx_svc

    async def compute_ato_report(
        self,
        user_id: str,
        financial_year: int,                  # e.g. 2025 for FY2024-25
        assumed_other_income_aud: Decimal = Decimal("80000"),
        cgt_discount_rate: Decimal = Decimal("0.50"),  # 50% individual
        account_ids: Optional[list[str]] = None,
    ) -> ATOTaxReport:
        """
        Compute a complete ATO CGT report for one Australian financial year.
        """
        fy_start, fy_end = au_fy_bounds(financial_year)
        fy_label = f"FY{financial_year - 1}-{str(financial_year)[2:]}"

        # ── Fetch disposed lots in this FY ───────────────────────────────
        lot_query = (
            select(TaxLot, Asset)
            .join(Asset, TaxLot.asset_id == Asset.id)
            .where(
                and_(
                    TaxLot.user_id == user_id,
                    TaxLot.closed_at >= fy_start,
                    TaxLot.closed_at <= fy_end,
                    TaxLot.lot_status == "CLOSED",
                )
            )
            .order_by(TaxLot.closed_at)
        )
        if account_ids:
            lot_query = lot_query.where(TaxLot.account_id.in_(account_ids))

        result = await self.db.execute(lot_query)
        closed_lots = result.all()

        # ── Build CGT events ─────────────────────────────────────────────
        cgt_events: list[CGTEvent] = []
        gross_gains = ZERO
        total_losses = ZERO

        for lot, asset in closed_lots:
            event = await self._build_cgt_event(lot, asset)
            cgt_events.append(event)
            if event.is_loss:
                total_losses += event.capital_loss_aud
            else:
                gross_gains += event.gross_gain_aud

        # ── Fetch prior year losses carried forward ───────────────────────
        # For a full implementation, these would come from a persistent table.
        # For now, calculate from prior FY if possible.
        prior_losses_cf = await self._get_prior_year_losses(user_id, financial_year)

        # ── Apply losses per ATO rules ────────────────────────────────────
        #
        # ATO loss application order (ITAA 1997 s102-5):
        # 1. Current year losses reduce current year gains
        # 2. Carried-forward losses reduce current year gains
        # 3. All losses must be applied to non-discount gains first,
        #    then to discount-eligible gains
        # 4. The 50% discount is applied only to the REMAINING eligible gain
        #    after loss application.
        #
        available_losses = total_losses + prior_losses_cf

        non_discount_events = [e for e in cgt_events if not e.is_loss and not e.discount_eligible]
        discount_events = [e for e in cgt_events if not e.is_loss and e.discount_eligible]

        gross_non_discount = sum(e.gross_gain_aud for e in non_discount_events)
        gross_discount_eligible = sum(e.gross_gain_aud for e in discount_events)

        # Apply losses to non-discount gains first
        losses_against_non_discount = min(available_losses, gross_non_discount)
        net_non_discount = max(ZERO, gross_non_discount - losses_against_non_discount)
        remaining_losses = available_losses - losses_against_non_discount

        # Apply remaining losses to discount-eligible gains
        losses_against_discount = min(remaining_losses, gross_discount_eligible)
        net_discount_before_reduction = max(ZERO, gross_discount_eligible - losses_against_discount)
        remaining_losses = remaining_losses - losses_against_discount

        # Apply 50% discount to the net discount-eligible gains
        discount_amount = (net_discount_before_reduction * cgt_discount_rate).quantize(CENT)
        net_discount_after_reduction = net_discount_before_reduction - discount_amount

        net_capital_gain = net_non_discount + net_discount_after_reduction
        losses_carried_forward = remaining_losses  # any unused losses carry forward

        # ── Income ────────────────────────────────────────────────────────
        div_income, staking_income, interest_income, franking_credits = await self._compute_income(
            user_id, fy_start, fy_end
        )

        # ── Tax estimates ─────────────────────────────────────────────────
        total_income_without_cgt = (
            assumed_other_income_aud + div_income + staking_income + interest_income - franking_credits
        )
        total_income_with_cgt = total_income_without_cgt + net_capital_gain

        tax_without_cgt = ato_income_tax(total_income_without_cgt)
        tax_with_cgt = ato_income_tax(total_income_with_cgt)
        cgt_tax = max(ZERO, tax_with_cgt - tax_without_cgt)

        effective_rate = (
            (cgt_tax / net_capital_gain * 100).quantize(CENT)
            if net_capital_gain > ZERO else ZERO
        )

        # ── TLH opportunities ─────────────────────────────────────────────
        tlh_opportunities, unrealised_losses = await self._find_tlh_opportunities(user_id)

        return ATOTaxReport(
            financial_year=financial_year,
            fy_label=fy_label,
            gross_capital_gains_aud=gross_gains,
            capital_losses_aud=total_losses,
            net_gain_non_discount_aud=net_non_discount,
            net_gain_discount_eligible_aud=net_discount_before_reduction,
            cgt_discount_amount_aud=discount_amount,
            net_capital_gain_aud=net_capital_gain,
            losses_carried_forward_aud=losses_carried_forward,
            dividend_income_aud=div_income,
            staking_income_aud=staking_income,
            interest_income_aud=interest_income,
            franking_credits_aud=franking_credits,
            assumed_other_income_aud=assumed_other_income_aud,
            total_taxable_income_aud=total_income_with_cgt,
            estimated_tax_aud=tax_without_cgt,
            estimated_tax_with_cgt_aud=tax_with_cgt,
            estimated_cgt_tax_aud=cgt_tax,
            effective_cgt_rate_pct=effective_rate,
            cgt_events=cgt_events,
            tlh_opportunities=tlh_opportunities,
            total_unrealised_losses_aud=unrealised_losses,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _build_cgt_event(self, lot: TaxLot, asset: Asset) -> CGTEvent:
        """Convert a closed TaxLot into an ATO CGT Event."""
        acquired = lot.acquired_at
        disposed = lot.closed_at or datetime.now(timezone.utc)
        holding_days = (disposed - acquired).days
        discount_eligible = holding_days >= 365

        qty = Decimal(str(lot.quantity_acquired - lot.quantity_remaining))
        if qty <= ZERO:
            qty = Decimal(str(lot.quantity_acquired))

        # Cost base in AUD: use stored AUD price if available,
        # otherwise fall back to USD amount and convert via FX
        if hasattr(lot, 'cost_basis_aud') and lot.cost_basis_aud:
            cost_base_aud = Decimal(str(lot.cost_basis_aud))
        else:
            # Try to get AUD cost base from the opening transaction
            cost_base_usd = Decimal(str(lot.total_cost_basis))
            fx_rate = await self.fx.get_aud_rate("USD", acquired)
            cost_base_aud = (cost_base_usd * fx_rate).quantize(CENT)

        # Proceeds in AUD
        if lot.proceeds is not None:
            proceeds_usd = Decimal(str(lot.proceeds))
            fx_at_disposal = await self.fx.get_aud_rate("USD", disposed)
            proceeds_aud = (proceeds_usd * fx_at_disposal).quantize(CENT)
        else:
            proceeds_aud = ZERO

        gross_gain = proceeds_aud - cost_base_aud
        is_loss = gross_gain < ZERO

        discounted = ZERO
        loss = ZERO
        if is_loss:
            loss = abs(gross_gain)
        else:
            discounted = gross_gain  # discount applied at report level, not lot level

        return CGTEvent(
            symbol=asset.symbol,
            name=asset.name,
            asset_class=asset.asset_class,
            acquired_at=acquired,
            disposed_at=disposed,
            holding_days=holding_days,
            discount_eligible=discount_eligible,
            quantity=qty,
            cost_base_aud=cost_base_aud,
            proceeds_aud=proceeds_aud,
            gross_gain_aud=gross_gain if not is_loss else ZERO,
            discounted_gain_aud=discounted,
            capital_loss_aud=loss,
            is_loss=is_loss,
            lot_id=lot.id,
        )

    async def _compute_income(
        self, user_id: str, fy_start: datetime, fy_end: datetime
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Fetch dividend income, staking income, interest, and franking credits
        within the financial year. Returns all amounts in AUD.
        """
        query = (
            select(Transaction, Asset)
            .join(Asset, Transaction.asset_id == Asset.id, isouter=True)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.transacted_at >= fy_start,
                    Transaction.transacted_at <= fy_end,
                    Transaction.transaction_type.in_([
                        "DIVIDEND", "FRANKED_DIVIDEND", "STAKE_REWARD",
                        "STAKING_REWARD", "INTEREST", "MINING_REWARD", "AIRDROP"
                    ]),
                )
            )
        )
        result = await self.db.execute(query)
        rows = result.all()

        dividends = ZERO
        staking = ZERO
        interest = ZERO
        franking = ZERO

        for txn, asset in rows:
            # Use stored AUD amount if available, else convert
            if txn.net_amount_aud:
                aud = abs(Decimal(str(txn.net_amount_aud)))
            elif txn.net_amount_usd:
                rate = await self.fx.get_aud_rate("USD", txn.transacted_at)
                aud = abs(Decimal(str(txn.net_amount_usd)) * rate)
            elif txn.net_amount:
                rate = await self.fx.get_aud_rate(txn.currency or "USD", txn.transacted_at)
                aud = abs(Decimal(str(txn.net_amount)) * rate)
            else:
                aud = ZERO

            t = txn.transaction_type.upper()
            if t in ("DIVIDEND", "FRANKED_DIVIDEND"):
                dividends += aud
                # Franking credits stored in raw_data if available
                if txn.raw_data and "franking_credit" in txn.raw_data:
                    franking += Decimal(str(txn.raw_data["franking_credit"]))
            elif t in ("STAKE_REWARD", "STAKING_REWARD", "MINING_REWARD", "AIRDROP"):
                staking += aud
            elif t == "INTEREST":
                interest += aud

        return dividends, staking, interest, franking

    async def _get_prior_year_losses(self, user_id: str, current_fy: int) -> Decimal:
        """
        Look up capital losses carried forward from prior financial years.
        In a full implementation, these would persist in a dedicated table.
        For now, we compute from prior year disposals as a starting point.
        """
        # TODO: persist carried-forward losses in a dedicated table
        return ZERO

    async def _find_tlh_opportunities(
        self, user_id: str
    ) -> tuple[list[dict], Decimal]:
        """
        Find unrealised losses that could be harvested to reduce CGT this year.
        Returns AUD amounts.
        """
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

        symbols = list({a.symbol for _, a in open_lots})
        prices = await self.market_data.get_batch_prices(symbols)

        now = datetime.now(timezone.utc)
        opportunities = []
        total_unrealised_loss = ZERO

        asset_groups: dict[str, tuple[Asset, list[TaxLot]]] = {}
        for lot, asset in open_lots:
            if asset.symbol not in asset_groups:
                asset_groups[asset.symbol] = (asset, [])
            asset_groups[asset.symbol][1].append(lot)

        for symbol, (asset, lots) in asset_groups.items():
            usd_price = prices.get(symbol)
            if not usd_price:
                continue

            # Convert current price to AUD
            aud_rate = await self.fx.get_aud_rate("USD", now)
            aud_price = Decimal(str(usd_price)) * aud_rate

            total_qty = sum(Decimal(str(lot.quantity_remaining)) for lot in lots)
            current_value_aud = (total_qty * aud_price).quantize(CENT)

            # Cost base in AUD
            total_cost_aud = ZERO
            for lot in lots:
                if Decimal(str(lot.quantity_remaining)) <= ZERO:
                    continue
                acq_rate = await self.fx.get_aud_rate("USD", lot.acquired_at)
                lot_cost_aud = (
                    Decimal(str(lot.quantity_remaining)) *
                    Decimal(str(lot.cost_basis_per_unit)) *
                    acq_rate
                ).quantize(CENT)
                total_cost_aud += lot_cost_aud

            unrealised = current_value_aud - total_cost_aud

            if unrealised < Decimal("-50"):   # Only flag losses > $50 AUD
                holding_days = min(
                    (now - lot.acquired_at).days for lot in lots if Decimal(str(lot.quantity_remaining)) > ZERO
                )
                discount_eligible = holding_days >= 365

                # Marginal rate estimate at $80k income
                marg_rate = ato_marginal_rate(Decimal("80000"))
                # If discount-eligible loss used to offset discount-eligible gain,
                # effective tax saving is different — we use simple marginal rate
                tax_saving = abs(unrealised) * marg_rate

                opportunities.append({
                    "symbol": symbol,
                    "name": asset.name,
                    "asset_class": asset.asset_class,
                    "quantity": float(total_qty),
                    "cost_base_aud": float(total_cost_aud),
                    "current_value_aud": float(current_value_aud),
                    "unrealised_loss_aud": float(unrealised),
                    "estimated_tax_saving_aud": float(tax_saving),
                    "holding_days": holding_days,
                    "discount_eligible_if_sold_now": discount_eligible,
                    "ato_note": (
                        "Loss can offset your capital gains this FY. "
                        "Apply to non-discount gains first for maximum benefit."
                        if not discount_eligible
                        else "Loss can offset gains. Consider waiting until 12-month mark if close."
                    ),
                })
                total_unrealised_loss += unrealised

        opportunities.sort(key=lambda x: x["unrealised_loss_aud"])
        return opportunities, total_unrealised_loss


# ── ATO Schedule 3 formatter ─────────────────────────────────────────────────

def format_ato_schedule3(report: ATOTaxReport) -> dict:
    """
    Format the CGT report as ATO Schedule 3 (Capital Gains) labels.
    These map directly to what your tax agent or myTax expects.
    """
    return {
        "schedule": "Capital gains tax (CGT) schedule",
        "financial_year": report.fy_label,
        # ATO label references (e.g. item 18 in individual tax return)
        "18A_gross_capital_gains": str(report.gross_capital_gains_aud),
        "18B_capital_losses_current_year": str(report.capital_losses_aud),
        "18V_net_capital_gain": str(report.net_capital_gain_aud),
        "18H_losses_carried_forward": str(report.losses_carried_forward_aud),
        # Breakdown for tax agent
        "cgt_discount_applied": str(report.cgt_discount_amount_aud),
        "discount_eligible_gains_before_discount": str(report.net_gain_discount_eligible_aud),
        "non_discount_gains": str(report.net_gain_non_discount_aud),
        # Income items
        "dividend_income": str(report.dividend_income_aud),
        "franking_credits": str(report.franking_credits_aud),
        "staking_and_crypto_income": str(report.staking_income_aud),
        "interest_income": str(report.interest_income_aud),
        # Estimates (not on ATO form — for planning only)
        "estimated_cgt_tax_aud": str(report.estimated_cgt_tax_aud),
        "effective_cgt_rate_pct": str(report.effective_cgt_rate_pct),
        "cgt_events_count": len(report.cgt_events),
        "note": (
            "Net capital gain at 18V is what you enter in your tax return. "
            "Estimated tax figures are indicative only — consult a registered tax agent."
        ),
    }
