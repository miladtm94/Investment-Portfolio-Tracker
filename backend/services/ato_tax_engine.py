"""Australian investment tax calculations.

The engine deliberately rebuilds parcels from the transaction ledger.  The
application historically queried ``tax_lots`` even though no importer creates
those rows, which made every Tax Centre report empty.

Amounts are calculated in AUD at the transaction date.  The report is an
investment-tax workpaper for an Australian-resident individual, not an ATO
assessment: residency, private health insurance, HELP and unusual CGT events
can change the final liability.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.fx_service import FXService
from shared.models import Account, Asset, Transaction

ZERO = Decimal("0")
CENT = Decimal("0.01")
QTY = Decimal("0.0000000001")
SUPPORTED_METHODS = {"FIFO", "LIFO", "HIFO", "TAX_OPTIMAL"}


def money(value: Decimal | float | int | str | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def au_financial_year(dt: datetime) -> int:
    """Return the end year (2025) for an Australian FY (2024-25)."""
    return dt.year + 1 if dt.month >= 7 else dt.year


def au_fy_bounds(fy_end_year: int) -> tuple[datetime, datetime]:
    return (
        datetime(fy_end_year - 1, 7, 1, tzinfo=timezone.utc),
        datetime(fy_end_year, 6, 30, 23, 59, 59, 999999, tzinfo=timezone.utc),
    )


@dataclass(frozen=True)
class TaxRules:
    fy_end_year: int
    brackets: tuple[tuple[Decimal, Decimal], ...]
    medicare_lower: Decimal
    medicare_upper: Decimal
    cgt_discount_rate: Decimal = Decimal("0.50")
    lito_max: Decimal = Decimal("700")


def rules_for_fy(fy_end_year: int) -> TaxRules:
    """Legislated resident-individual settings, selected by income year."""
    if fy_end_year <= 2024:
        brackets = ((Decimal("18200"), ZERO), (Decimal("45000"), Decimal("0.19")),
                    (Decimal("120000"), Decimal("0.325")), (Decimal("180000"), Decimal("0.37")),
                    (Decimal("999999999"), Decimal("0.45")))
        if fy_end_year == 2024:
            medicare = (Decimal("26000"), Decimal("32500"))
        elif fy_end_year == 2023:
            medicare = (Decimal("24276"), Decimal("30345"))
        elif fy_end_year == 2022:
            medicare = (Decimal("23365"), Decimal("29207"))
        else:
            medicare = (Decimal("23226"), Decimal("29033"))
    elif fy_end_year == 2025:
        brackets = ((Decimal("18200"), ZERO), (Decimal("45000"), Decimal("0.16")),
                    (Decimal("135000"), Decimal("0.30")), (Decimal("190000"), Decimal("0.37")),
                    (Decimal("999999999"), Decimal("0.45")))
        medicare = (Decimal("27222"), Decimal("34027"))
    elif fy_end_year in (2026, 2027):
        first_rate = Decimal("0.15") if fy_end_year == 2027 else Decimal("0.16")
        brackets = ((Decimal("18200"), ZERO), (Decimal("45000"), first_rate),
                    (Decimal("135000"), Decimal("0.30")), (Decimal("190000"), Decimal("0.37")),
                    (Decimal("999999999"), Decimal("0.45")))
        medicare = (Decimal("28011"), Decimal("35013"))
    else:
        # The 14% first rate is legislated from 2027-28. Thresholds that are
        # indexed annually remain visible/editable in the UI as an estimate.
        brackets = ((Decimal("18200"), ZERO), (Decimal("45000"), Decimal("0.14")),
                    (Decimal("135000"), Decimal("0.30")), (Decimal("190000"), Decimal("0.37")),
                    (Decimal("999999999"), Decimal("0.45")))
        medicare = (Decimal("28011"), Decimal("35013"))
    return TaxRules(fy_end_year, brackets, *medicare)


def basic_income_tax(taxable_income: Decimal, rules: TaxRules) -> Decimal:
    """Resident individual income tax before offsets and Medicare levy."""
    income = max(ZERO, Decimal(taxable_income))
    tax = ZERO
    lower = ZERO
    for upper, rate in rules.brackets:
        if income <= lower:
            break
        tax += (min(income, upper) - lower) * rate
        lower = upper
    return money(tax)


def low_income_tax_offset(taxable_income: Decimal, maximum: Decimal = Decimal("700")) -> Decimal:
    income = max(ZERO, Decimal(taxable_income))
    if income <= Decimal("37500"):
        return maximum
    if income <= Decimal("45000"):
        return max(ZERO, maximum - (income - Decimal("37500")) * Decimal("0.05"))
    if income <= Decimal("66667"):
        return max(ZERO, Decimal("325") - (income - Decimal("45000")) * Decimal("0.015"))
    return ZERO


def medicare_levy(taxable_income: Decimal, rules: TaxRules, exemption_pct: Decimal = ZERO) -> Decimal:
    income = max(ZERO, Decimal(taxable_income))
    if income <= rules.medicare_lower:
        levy = ZERO
    elif income < rules.medicare_upper:
        levy = min(income * Decimal("0.02"), (income - rules.medicare_lower) * Decimal("0.10"))
    else:
        levy = income * Decimal("0.02")
    factor = max(ZERO, Decimal("1") - min(Decimal("100"), exemption_pct) / Decimal("100"))
    return money(levy * factor)


@dataclass
class TaxCalculation:
    taxable_income: Decimal
    basic_tax: Decimal
    lito: Decimal
    medicare_levy: Decimal
    non_refundable_offsets: Decimal
    refundable_offsets: Decimal
    tax_after_offsets: Decimal
    tax_withheld: Decimal
    estimated_amount_due: Decimal
    estimated_refund: Decimal


def calculate_tax(
    taxable_income: Decimal,
    rules: TaxRules,
    *,
    franking_offsets: Decimal = ZERO,
    foreign_tax_offsets: Decimal = ZERO,
    other_offsets: Decimal = ZERO,
    tax_withheld: Decimal = ZERO,
    medicare_exemption_pct: Decimal = ZERO,
) -> TaxCalculation:
    taxable = money(max(ZERO, taxable_income))
    basic = basic_income_tax(taxable, rules)
    lito = money(min(basic, low_income_tax_offset(taxable, rules.lito_max)))
    levy = medicare_levy(taxable, rules, medicare_exemption_pct)
    after_lito = max(ZERO, basic - lito) + levy
    # FITO may also reduce Medicare liabilities. Other user-entered offsets are
    # treated conservatively as non-refundable.
    non_ref = money(max(ZERO, foreign_tax_offsets) + max(ZERO, other_offsets))
    after_non_ref = max(ZERO, after_lito - non_ref)
    refundable = money(max(ZERO, franking_offsets))
    after_offsets = money(after_non_ref - refundable)
    withheld = money(max(ZERO, tax_withheld))
    balance = after_offsets - withheld
    return TaxCalculation(
        taxable, basic, lito, levy, non_ref, refundable, after_offsets, withheld,
        money(max(ZERO, balance)), money(max(ZERO, -balance)),
    )


def _anniversary(acquired: date) -> date:
    try:
        return acquired.replace(year=acquired.year + 1)
    except ValueError:  # 29 February
        return acquired.replace(year=acquired.year + 1, day=28)


def cgt_discount_eligible(acquired: datetime, disposed: datetime) -> bool:
    # ATO excludes both acquisition and disposal days. Selling on the first
    # anniversary is therefore too early; disposal must be after it.
    return disposed.date() > _anniversary(acquired.date())


@dataclass
class InventoryLot:
    transaction_id: str
    account_id: str
    acquired_at: datetime
    quantity_remaining: Decimal
    cost_per_unit_aud: Decimal


@dataclass
class CGTEvent:
    symbol: str
    name: str
    asset_class: str
    account_name: str
    acquired_at: datetime
    disposed_at: datetime
    holding_days: int
    discount_eligible: bool
    quantity: Decimal
    cost_base_aud: Decimal
    proceeds_aud: Decimal
    gross_gain_aud: Decimal
    capital_loss_aud: Decimal
    cgt_event_type: str = "A1"
    opening_transaction_id: Optional[str] = None
    closing_transaction_id: Optional[str] = None

    @property
    def net_gain_aud(self) -> Decimal:
        return self.gross_gain_aud

    @property
    def is_loss(self) -> bool:
        return self.gross_gain_aud < ZERO


@dataclass
class IncomeSummary:
    franked_dividends: Decimal = ZERO
    unfranked_dividends: Decimal = ZERO
    foreign_dividends: Decimal = ZERO
    franking_credits: Decimal = ZERO
    foreign_tax_paid: Decimal = ZERO
    interest: Decimal = ZERO
    staking: Decimal = ZERO

    @property
    def cash_dividends(self) -> Decimal:
        return self.franked_dividends + self.unfranked_dividends + self.foreign_dividends

    @property
    def assessable_dividends(self) -> Decimal:
        return self.cash_dividends + self.franking_credits


@dataclass
class ATOTaxReport:
    financial_year: int
    fy_label: str
    cost_method: str
    gross_capital_gains_aud: Decimal
    capital_losses_current_aud: Decimal
    capital_losses_prior_aud: Decimal
    capital_losses_applied_aud: Decimal
    discount_gains_before_discount: Decimal
    cgt_discount_applied: Decimal
    net_capital_gain_aud: Decimal
    capital_losses_carried_forward: Decimal
    dividend_income_aud: Decimal
    franked_dividends_aud: Decimal
    unfranked_dividends_aud: Decimal
    foreign_dividends_aud: Decimal
    assessable_dividend_income_aud: Decimal
    franking_credits_aud: Decimal
    foreign_tax_paid_aud: Decimal
    staking_income_aud: Decimal
    interest_income_aud: Decimal
    investment_deductions_aud: Decimal
    other_income_aud: Decimal
    other_deductions_aud: Decimal
    total_taxable_income_aud: Decimal
    basic_income_tax_aud: Decimal
    lito_aud: Decimal
    medicare_levy_aud: Decimal
    franking_tax_offset_aud: Decimal
    foreign_tax_offsets_aud: Decimal
    other_tax_offsets_aud: Decimal
    tax_withheld_aud: Decimal
    net_tax_before_withholding_aud: Decimal
    estimated_tax_payable_aud: Decimal
    estimated_refund_aud: Decimal
    estimated_tax_on_investments_aud: Decimal
    effective_tax_rate: Decimal
    cgt_events: list[CGTEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    optimization: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)

    # Compatibility aliases used by the original router.
    @property
    def losses_carried_forward_aud(self) -> Decimal:
        return self.capital_losses_carried_forward

    @property
    def cgt_discount_amount_aud(self) -> Decimal:
        return self.cgt_discount_applied

    @property
    def capital_losses_aud(self) -> Decimal:
        return self.capital_losses_current_aud


class ATOTaxEngine:
    def __init__(self, db: AsyncSession, fx_svc: Optional[FXService] = None):
        self.db = db
        self.fx = fx_svc or FXService()

    async def close(self) -> None:
        await self.fx.close()

    async def compute_ato_report(
        self,
        user_id: str,
        fy_end_year: int,
        cost_method: str = "FIFO",
        settings: Optional[dict[str, Any]] = None,
        account_ids: Optional[list[str]] = None,
    ) -> ATOTaxReport:
        method = cost_method.upper()
        if method not in SUPPORTED_METHODS:
            raise ValueError(f"Unsupported cost method: {cost_method}")
        inputs = settings or {}
        fy_start, fy_end = au_fy_bounds(fy_end_year)
        rules = rules_for_fy(fy_end_year)

        query = (
            select(Transaction, Asset, Account)
            .join(Account, Transaction.account_id == Account.id)
            .join(Asset, Transaction.asset_id == Asset.id, isouter=True)
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.transacted_at <= fy_end,
                    Transaction.status == "SETTLED",
                    Account.is_taxable.is_(True),
                    # Demo portfolios are deliberately kept outside the real
                    # dashboard and must not leak into an ATO workpaper.
                    Account.name.not_like("Demo - %"),
                )
            )
            .order_by(Transaction.transacted_at, Transaction.id)
        )
        if account_ids:
            query = query.where(Transaction.account_id.in_(account_ids))
        rows = (await self.db.execute(query)).all()

        events, event_warnings = await self._build_events(rows, fy_start, fy_end, method)
        income, income_warnings = await self._income(rows, fy_start, fy_end, inputs)
        cgt = self._aggregate_cgt(events, inputs, rules)

        investment_deductions = money(inputs.get("investment_deductions_aud"))
        other_income = money(inputs.get("other_income_aud"))
        other_deductions = money(inputs.get("other_deductions_aud"))
        taxable_income = max(
            ZERO,
            other_income + income.assessable_dividends + income.interest + income.staking
            + cgt["net_gain"] - investment_deductions - other_deductions,
        )
        eligible_franking = income.franking_credits if inputs.get("franking_credits_eligible", True) else ZERO
        foreign_offset = income.foreign_tax_paid + money(inputs.get("other_foreign_tax_offsets_aud"))
        calculation = calculate_tax(
            taxable_income,
            rules,
            franking_offsets=eligible_franking,
            foreign_tax_offsets=foreign_offset,
            other_offsets=money(inputs.get("other_tax_offsets_aud")),
            tax_withheld=money(inputs.get("tax_withheld_aud")),
            medicare_exemption_pct=Decimal(str(inputs.get("medicare_levy_exemption_pct", 0))),
        )
        baseline_taxable = max(ZERO, other_income - other_deductions)
        baseline = calculate_tax(
            baseline_taxable,
            rules,
            other_offsets=money(inputs.get("other_tax_offsets_aud")),
            tax_withheld=money(inputs.get("tax_withheld_aud")),
            medicare_exemption_pct=Decimal(str(inputs.get("medicare_levy_exemption_pct", 0))),
        )
        investment_tax = money(calculation.tax_after_offsets - baseline.tax_after_offsets)

        optimization: dict[str, Any] = {
            "losses_applied_to_non_discount_gains_first": True,
            "selected_cost_method": method,
            "recommendations": [],
        }
        if method != "TAX_OPTIMAL":
            optimal_events, _ = await self._build_events(rows, fy_start, fy_end, "TAX_OPTIMAL")
            optimal_cgt = self._aggregate_cgt(optimal_events, inputs, rules)
            reduction = max(ZERO, cgt["net_gain"] - optimal_cgt["net_gain"])
            marginal = self._marginal_rate(taxable_income, rules)
            saving = money(reduction * marginal)
            optimization.update({
                "tax_optimal_net_capital_gain_aud": float(optimal_cgt["net_gain"]),
                "potential_taxable_gain_reduction_aud": float(reduction),
                "estimated_tax_saving_aud": float(saving),
            })
            if reduction > ZERO:
                optimization["recommendations"].append(
                    "Review the TAX_OPTIMAL parcel selection. Use it only where your records can identify the selected parcels."
                )
        if cgt["losses_cf"] > ZERO:
            optimization["recommendations"].append(
                "Carry forward unapplied capital losses; they cannot reduce salary or dividend income."
            )
        if fy_end >= datetime.now(timezone.utc):
            optimization["recommendations"].append(
                "Before 30 June, review unrealised losses and near-12-month holdings with a registered tax adviser; Part IVA can apply to wash-sale arrangements."
            )

        warnings = event_warnings + income_warnings
        if not rows:
            warnings.append("No settled transactions were found in taxable accounts through this financial year.")
        elif any(
            txn.currency and txn.currency.upper() != "AUD" and txn.net_amount_aud is None
            for txn, _asset, _account in rows
        ):
            warnings.append(
                "Some foreign-currency transactions had no stored AUD value, so historical FX was fetched during this report. Verify rates before lodging."
            )
        if fy_end_year > 2027:
            warnings.append(
                "Future-year results are indicative only: Medicare thresholds and the CGT reforms applying to gains accruing from 1 July 2027 require year-specific implementation before lodging."
            )
        if not inputs.get("resident_full_year", True):
            warnings.append("This estimate uses resident rates and is not valid for part-year or foreign residency without professional adjustment.")
        warnings.append(
            "Parcel methods rebuild selections from the full imported history. Confirm they match parcels used in any previously lodged returns."
        )

        effective = money((calculation.tax_after_offsets / taxable_income * Decimal("100")) if taxable_income else ZERO)
        return ATOTaxReport(
            financial_year=fy_end_year,
            fy_label=f"FY{fy_end_year - 1}-{str(fy_end_year)[-2:]}",
            cost_method=method,
            gross_capital_gains_aud=cgt["gross_gains"],
            capital_losses_current_aud=cgt["current_losses"],
            capital_losses_prior_aud=cgt["prior_losses"],
            capital_losses_applied_aud=cgt["losses_applied"],
            discount_gains_before_discount=cgt["discount_before"],
            cgt_discount_applied=cgt["discount"],
            net_capital_gain_aud=cgt["net_gain"],
            capital_losses_carried_forward=cgt["losses_cf"],
            dividend_income_aud=income.cash_dividends,
            franked_dividends_aud=income.franked_dividends,
            unfranked_dividends_aud=income.unfranked_dividends,
            foreign_dividends_aud=income.foreign_dividends,
            assessable_dividend_income_aud=income.assessable_dividends,
            franking_credits_aud=income.franking_credits,
            foreign_tax_paid_aud=income.foreign_tax_paid,
            staking_income_aud=income.staking,
            interest_income_aud=income.interest,
            investment_deductions_aud=investment_deductions,
            other_income_aud=other_income,
            other_deductions_aud=other_deductions,
            total_taxable_income_aud=money(taxable_income),
            basic_income_tax_aud=calculation.basic_tax,
            lito_aud=calculation.lito,
            medicare_levy_aud=calculation.medicare_levy,
            franking_tax_offset_aud=money(eligible_franking),
            foreign_tax_offsets_aud=money(foreign_offset),
            other_tax_offsets_aud=money(inputs.get("other_tax_offsets_aud")),
            tax_withheld_aud=money(inputs.get("tax_withheld_aud")),
            net_tax_before_withholding_aud=calculation.tax_after_offsets,
            estimated_tax_payable_aud=calculation.estimated_amount_due,
            estimated_refund_aud=calculation.estimated_refund,
            estimated_tax_on_investments_aud=investment_tax,
            effective_tax_rate=effective,
            cgt_events=events,
            warnings=warnings,
            optimization=optimization,
            rules={
                "fy_end_year": fy_end_year,
                "cgt_discount_rate": float(rules.cgt_discount_rate),
                "medicare_lower_threshold": float(rules.medicare_lower),
                "medicare_upper_threshold": float(rules.medicare_upper),
                "income_tax_brackets": [
                    {"upper": float(upper), "rate": float(rate)} for upper, rate in rules.brackets
                ],
            },
        )

    async def _aud(self, txn: Transaction, value: Decimal, *, stored: Optional[Decimal] = None) -> Decimal:
        if stored is not None:
            return abs(Decimal(str(stored)))
        rate = Decimal(str(txn.fx_rate_to_aud)) if txn.fx_rate_to_aud else await self.fx.get_aud_rate(txn.currency or "AUD", txn.transacted_at)
        return abs(value) * rate

    async def _transaction_value_aud(self, txn: Transaction, qty: Decimal) -> Decimal:
        if txn.net_amount_aud is not None and Decimal(str(txn.net_amount_aud)) != ZERO:
            return abs(Decimal(str(txn.net_amount_aud)))
        if txn.net_amount is not None and Decimal(str(txn.net_amount)) != ZERO:
            return await self._aud(txn, Decimal(str(txn.net_amount)))
        price = Decimal(str(txn.price_per_unit_aud or 0))
        if not price and txn.price_per_unit is not None:
            price = await self._aud(txn, Decimal(str(txn.price_per_unit)))
        fees = await self._aud(txn, Decimal(str(txn.fees or 0)))
        gross = qty * price
        return gross - fees if txn.transaction_type.upper() == "SELL" else gross + fees

    async def _build_events(self, rows: list[Any], fy_start: datetime, fy_end: datetime, method: str) -> tuple[list[CGTEvent], list[str]]:
        inventory: dict[tuple[str, str], list[InventoryLot]] = defaultdict(list)
        events: list[CGTEvent] = []
        warnings: list[str] = []
        for txn, asset, account in rows:
            kind = txn.transaction_type.upper()
            if asset and kind == "SWAP" and fy_start <= txn.transacted_at <= fy_end:
                warnings.append(
                    f"{asset.symbol} swap on {txn.transacted_at.date()} needs disposal/acquisition detail and was not automatically calculated."
                )
            if not asset:
                continue
            key = (str(txn.account_id), str(asset.id))
            if kind == "SPLIT":
                ratio = Decimal(str(txn.split_ratio or 0))
                if ratio > ZERO:
                    for lot in inventory[key]:
                        lot.quantity_remaining *= ratio
                        lot.cost_per_unit_aud /= ratio
                elif fy_start <= txn.transacted_at <= fy_end:
                    warnings.append(f"{asset.symbol} split on {txn.transacted_at.date()} has no split ratio and was skipped.")
                continue
            if kind not in {"BUY", "SELL"}:
                continue
            qty = abs(Decimal(str(txn.quantity or 0)))
            if qty <= ZERO:
                warnings.append(f"{asset.symbol} {txn.transaction_type} on {txn.transacted_at.date()} has no quantity and was skipped.")
                continue
            value = await self._transaction_value_aud(txn, qty)
            if kind == "BUY":
                inventory[key].append(InventoryLot(str(txn.id), str(txn.account_id), txn.transacted_at, qty, value / qty))
                continue

            sell_unit = value / qty
            remaining = qty
            lots = inventory[key]

            def sort_key(lot: InventoryLot) -> Any:
                if method == "LIFO":
                    return (-lot.acquired_at.timestamp(),)
                if method == "HIFO":
                    return (-lot.cost_per_unit_aud, lot.acquired_at)
                if method == "TAX_OPTIMAL":
                    gain = sell_unit - lot.cost_per_unit_aud
                    taxable = gain * (Decimal("0.50") if gain > ZERO and cgt_discount_eligible(lot.acquired_at, txn.transacted_at) else Decimal("1"))
                    return (taxable, lot.acquired_at)
                return (lot.acquired_at,)

            for lot in sorted([lot for lot in lots if lot.quantity_remaining > ZERO], key=sort_key):
                if remaining <= ZERO:
                    break
                matched = min(remaining, lot.quantity_remaining)
                cost = money(matched * lot.cost_per_unit_aud)
                proceeds = money(matched * sell_unit)
                gain = money(proceeds - cost)
                if fy_start <= txn.transacted_at <= fy_end:
                    events.append(CGTEvent(
                        asset.symbol, asset.name, asset.asset_class, account.name,
                        lot.acquired_at, txn.transacted_at,
                        (txn.transacted_at.date() - lot.acquired_at.date()).days,
                        cgt_discount_eligible(lot.acquired_at, txn.transacted_at),
                        matched.quantize(QTY), cost, proceeds, gain, money(max(ZERO, -gain)),
                        opening_transaction_id=lot.transaction_id,
                        closing_transaction_id=str(txn.id),
                    ))
                lot.quantity_remaining -= matched
                remaining -= matched
            if remaining > QTY:
                warnings.append(
                    f"{asset.symbol} sale on {txn.transacted_at.date()} has {remaining.normalize()} unmatched units; import earlier buys/transfers before relying on this report."
                )
        return events, warnings

    def _aggregate_cgt(self, events: list[CGTEvent], inputs: dict[str, Any], rules: TaxRules) -> dict[str, Decimal]:
        non_discount = sum((e.gross_gain_aud for e in events if e.gross_gain_aud > ZERO and not e.discount_eligible), ZERO)
        discount_gains = sum((e.gross_gain_aud for e in events if e.gross_gain_aud > ZERO and e.discount_eligible), ZERO)
        non_discount += money(inputs.get("other_non_discount_capital_gains_aud"))
        discount_gains += money(inputs.get("other_discount_capital_gains_aud"))
        current_losses = sum((-e.gross_gain_aud for e in events if e.gross_gain_aud < ZERO), ZERO)
        current_losses += money(inputs.get("other_capital_losses_aud"))
        prior_losses = money(inputs.get("prior_year_capital_losses_aud"))
        available = current_losses + prior_losses
        against_other = min(available, non_discount)
        net_other = non_discount - against_other
        remaining = available - against_other
        against_discount = min(remaining, discount_gains)
        discount_before = discount_gains - against_discount
        remaining -= against_discount
        discount = money(discount_before * rules.cgt_discount_rate)
        net_gain = money(net_other + discount_before - discount)
        return {
            "gross_gains": money(non_discount + discount_gains),
            "current_losses": money(current_losses),
            "prior_losses": prior_losses,
            "losses_applied": money(against_other + against_discount),
            "discount_before": money(discount_before),
            "discount": discount,
            "net_gain": net_gain,
            "losses_cf": money(remaining),
        }

    async def _income(self, rows: list[Any], fy_start: datetime, fy_end: datetime, inputs: dict[str, Any]) -> tuple[IncomeSummary, list[str]]:
        result = IncomeSummary()
        warnings: list[str] = []
        for txn, asset, _account in rows:
            if not (fy_start <= txn.transacted_at <= fy_end):
                continue
            kind = txn.transaction_type.upper()
            if kind not in {"DIVIDEND", "FRANKED_DIVIDEND", "DISTRIBUTION", "INTEREST", "STAKE_REWARD", "STAKING_REWARD", "MINING_REWARD", "AIRDROP"}:
                continue
            if kind == "DISTRIBUTION":
                warnings.append(
                    f"{asset.symbol if asset else 'Managed fund'} distribution on {txn.transacted_at.date()} is treated as cash income; reconcile it to the annual AMMA tax statement."
                )
            # ATO income labels use the gross entitlement (before withholding).
            # Only use the stored net AUD value when no explicit gross amount
            # exists; passing it alongside gross_amount previously discarded the
            # gross value and understated dividends.
            has_explicit_gross = txn.gross_amount is not None and Decimal(str(txn.gross_amount)) != ZERO
            if has_explicit_gross:
                base = Decimal(str(txn.gross_amount))
                amount = money(await self._aud(txn, base))
            elif txn.net_amount_aud is not None:
                amount = money(abs(Decimal(str(txn.net_amount_aud))))
            elif txn.net_amount is not None:
                amount = money(await self._aud(txn, Decimal(str(txn.net_amount))))
            elif getattr(txn, "net_amount_usd", None) is not None:
                amount = money(
                    await self.fx.get_aud_rate("USD", txn.transacted_at)
                    * abs(Decimal(str(txn.net_amount_usd)))
                )
            elif txn.quantity is not None and (txn.dividend_per_share is not None or txn.price_per_unit is not None):
                payout = txn.dividend_per_share if txn.dividend_per_share is not None else txn.price_per_unit
                amount = money(await self._aud(txn, Decimal(str(txn.quantity)) * Decimal(str(payout))))
            else:
                amount = ZERO
            withheld = money(await self._aud(txn, Decimal(str(txn.tax_withheld or 0)))) if txn.tax_withheld else ZERO
            if not has_explicit_gross:
                amount += withheld
            if kind == "INTEREST":
                result.interest += amount
            elif kind in {"STAKE_REWARD", "STAKING_REWARD", "MINING_REWARD", "AIRDROP"}:
                result.staking += amount
            else:
                credit_raw = txn.franking_credit
                if credit_raw is None and txn.raw_data:
                    credit_raw = txn.raw_data.get("franking_credit")
                credit = money(await self._aud(txn, Decimal(str(credit_raw or 0))))
                is_foreign = bool(
                    asset
                    and (
                        (asset.country and asset.country.upper() not in {"AU", "AUS"})
                        or (not asset.country and (txn.currency or asset.currency or "AUD").upper() != "AUD")
                    )
                )
                if is_foreign:
                    result.foreign_dividends += amount
                    result.foreign_tax_paid += withheld
                elif credit > ZERO or kind == "FRANKED_DIVIDEND" or Decimal(str(txn.franking_pct or 0)) > ZERO:
                    frank_pct = Decimal(str(txn.franking_pct or 100))
                    if frank_pct > Decimal("1"):
                        frank_pct /= Decimal("100")
                    result.franked_dividends += money(amount * min(Decimal("1"), frank_pct))
                    result.unfranked_dividends += money(amount * max(ZERO, Decimal("1") - frank_pct))
                    result.franking_credits += credit
                    if credit == ZERO:
                        warnings.append(f"{asset.symbol if asset else 'Dividend'} on {txn.transacted_at.date()} is marked franked but has no franking credit amount.")
                else:
                    result.unfranked_dividends += amount

        result.franked_dividends += money(inputs.get("other_franked_dividends_aud"))
        result.unfranked_dividends += money(inputs.get("other_unfranked_dividends_aud"))
        result.foreign_dividends += money(inputs.get("other_foreign_dividends_aud"))
        result.franking_credits += money(inputs.get("other_franking_credits_aud"))
        result.foreign_tax_paid += money(inputs.get("foreign_tax_paid_aud"))
        result.interest += money(inputs.get("other_interest_income_aud"))
        result.staking += money(inputs.get("other_staking_income_aud"))
        for field_name in result.__dataclass_fields__:
            setattr(result, field_name, money(getattr(result, field_name)))
        return result, warnings

    @staticmethod
    def _marginal_rate(income: Decimal, rules: TaxRules) -> Decimal:
        for upper, rate in rules.brackets:
            if income <= upper:
                return rate + Decimal("0.02")
        return Decimal("0.47")


def format_ato_schedule3(report: ATOTaxReport) -> dict[str, Any]:
    """Individual return Item 18 labels (H total, A net, V losses)."""
    return {
        "schedule": "Individual tax return – Item 18 Capital gains",
        "financial_year": report.fy_label,
        "18H_total_current_year_capital_gains": str(report.gross_capital_gains_aud),
        "18A_net_capital_gain": str(report.net_capital_gain_aud),
        "18V_net_capital_losses_carried_forward": str(report.capital_losses_carried_forward),
        "current_year_capital_losses": str(report.capital_losses_current_aud),
        "prior_year_losses_applied": str(report.capital_losses_prior_aud),
        "total_cgt_discount_applied": str(report.cgt_discount_applied),
        "11S_unfranked_dividends": str(report.unfranked_dividends_aud),
        "11T_franked_dividends": str(report.franked_dividends_aud),
        "11U_franking_credits": str(report.franking_credits_aud),
        "cgt_events_count": len(report.cgt_events),
        "warnings": report.warnings,
        "note": "Use as a workpaper and reconcile it to broker and dividend statements before lodging.",
    }
