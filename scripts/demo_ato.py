"""
InvestIQ — ATO CGT Demo
=======================
Standalone demonstration of the ATO tax engine and bank import parser.
No database, no Redis, no pip installs required — pure Python stdlib only.

Models an Australian investor with:
  • ASX shares (CBA, BHP, CSL)      — purchased via CommSec
  • US stocks (NVDA, TSLA)          — purchased via Stake (USD → AUD at RBA rates)
  • Crypto (BTC, ETH)               — purchased via Kraken

The script runs through FY2024-25 (1 July 2024 – 30 June 2025) and produces
the same output that the platform's /api/v1/tax/ato/summary endpoint would return.
"""

import csv
import hashlib
import io
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional

# ── Terminal colours ──────────────────────────────────────────────────────────
BOLD  = "\033[1m"
DIM   = "\033[2m"
GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
YELLOW= "\033[93m"
BLUE  = "\033[94m"
RESET = "\033[0m"

def aud(v) -> str:
    """Format a Decimal as AUD currency string."""
    v = Decimal(str(v))
    sign = "-" if v < 0 else ""
    return f"{sign}A${abs(v):,.2f}"

def pct(v) -> str:
    return f"{Decimal(str(v)):.2f}%"

def dt(d: str) -> datetime:
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)

ZERO = Decimal("0")
CENT = Decimal("0.01")

# ─────────────────────────────────────────────────────────────────────────────
# 1. ATO CALCULATION ENGINE (mirrors backend/services/ato_tax_engine.py)
# ─────────────────────────────────────────────────────────────────────────────

# ATO 2024-25 marginal tax brackets: (upper_threshold, base_tax, marginal_rate)
ATO_BRACKETS = [
    (Decimal("18200"),      Decimal("0"),      Decimal("0.00")),
    (Decimal("45000"),      Decimal("0"),      Decimal("0.19")),
    (Decimal("120000"),     Decimal("5092"),   Decimal("0.325")),
    (Decimal("180000"),     Decimal("29467"),  Decimal("0.37")),
    (Decimal("999999999"), Decimal("51667"),  Decimal("0.45")),
]
MEDICARE_LEVY = Decimal("0.02")
LITO_MAX      = Decimal("700")
LITO_FLOOR    = Decimal("37500")
LITO_CEIL     = Decimal("66667")


def ato_income_tax(income: Decimal) -> Decimal:
    """Compute 2024-25 ATO income tax + Medicare Levy, less LITO."""
    if income <= ZERO:
        return ZERO
    tax = ZERO
    prev = ZERO
    for threshold, _, rate in ATO_BRACKETS:
        if income <= prev:
            break
        band = min(income, threshold) - prev
        if rate > ZERO:
            tax += band * rate
        prev = threshold
    # LITO
    if income <= LITO_FLOOR:
        lito = LITO_MAX
    elif income <= LITO_CEIL:
        lito = LITO_MAX - (income - LITO_FLOOR) * Decimal("0.025")
    else:
        lito = ZERO
    tax = max(ZERO, tax - lito)
    medicare = income * MEDICARE_LEVY if income > Decimal("26000") else ZERO
    return (tax + medicare).quantize(CENT, rounding=ROUND_HALF_UP)


def ato_marginal_rate(income: Decimal) -> Decimal:
    for threshold, _, rate in ATO_BRACKETS:
        if income <= threshold:
            return rate + MEDICARE_LEVY
    return Decimal("0.47")


# ─────────────────────────────────────────────────────────────────────────────
# 2. SAMPLE FX RATES (RBA representative rates — AUD per 1 unit foreign)
#    In production these come from the RBA API, cached in Redis.
# ─────────────────────────────────────────────────────────────────────────────

# Approximate historical RBA AUD/USD rates for key trade dates
_FX = {
    "2022-08-10": Decimal("1.4621"),   # 1 USD = 1.4621 AUD
    "2022-11-15": Decimal("1.4802"),
    "2023-01-20": Decimal("1.4380"),
    "2023-03-05": Decimal("1.5021"),
    "2023-06-01": Decimal("1.4918"),
    "2023-07-14": Decimal("1.5102"),
    "2023-09-20": Decimal("1.5748"),
    "2023-11-30": Decimal("1.5401"),
    "2024-01-10": Decimal("1.5218"),
    "2024-02-28": Decimal("1.5360"),
    "2024-04-15": Decimal("1.5490"),
    "2024-05-20": Decimal("1.5201"),
    "2024-07-01": Decimal("1.4950"),   # FY2024-25 start
    "2024-08-15": Decimal("1.5105"),
    "2024-09-30": Decimal("1.4887"),
    "2024-10-22": Decimal("1.5302"),
    "2024-11-12": Decimal("1.5780"),
    "2024-12-01": Decimal("1.5925"),
    "2025-01-15": Decimal("1.6112"),
    "2025-02-10": Decimal("1.5935"),
    "2025-03-05": Decimal("1.5710"),
    "2025-04-20": Decimal("1.5488"),
    "2025-05-30": Decimal("1.5300"),
    "2025-06-28": Decimal("1.5150"),   # near FY end
}

def get_aud_rate(currency: str, date_str: str) -> Decimal:
    """Return AUD per 1 unit of `currency` (RBA-style lookup)."""
    if currency == "AUD":
        return Decimal("1.0")
    if currency == "USD":
        # Find closest available date
        for d in sorted(_FX.keys(), reverse=True):
            if d <= date_str:
                return _FX[d]
        return Decimal("1.52")  # fallback
    return Decimal("1.0")  # simplification for non-USD


# ─────────────────────────────────────────────────────────────────────────────
# 3. SAMPLE TRANSACTION LEDGER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Tx:
    date: str
    action: str           # BUY / SELL / DIVIDEND / STAKE_REWARD
    symbol: str
    name: str
    asset_class: str
    quantity: Decimal
    price: Decimal        # in native currency
    currency: str         # AUD or USD
    fee: Decimal = Decimal("0")
    franking_rate: Optional[Decimal] = None  # % e.g. 0.30 for 30% franked

    @property
    def date_str(self) -> str:
        return self.date

    @property
    def net_amount_aud(self) -> Decimal:
        fx = get_aud_rate(self.currency, self.date)
        gross = self.quantity * self.price * fx
        return (gross + self.fee * fx).quantize(CENT)

    @property
    def cost_basis_aud(self) -> Decimal:
        """ATO cost base element 1: money paid, including brokerage."""
        fx = get_aud_rate(self.currency, self.date)
        return ((self.quantity * self.price + self.fee) * fx).quantize(CENT)

    @property
    def proceeds_aud(self) -> Decimal:
        """Proceeds: money received less brokerage (cost base element 2 of seller)."""
        fx = get_aud_rate(self.currency, self.date)
        return ((self.quantity * self.price - self.fee) * fx).quantize(CENT)


LEDGER: list[Tx] = [
    # ── ASX shares via CommSec (AUD) ──────────────────────────────────────────
    Tx("2022-08-10", "BUY",      "CBA.AX", "Commonwealth Bank",  "AU_EQUITY", Decimal("50"),  Decimal("103.20"), "AUD", Decimal("19.95")),
    Tx("2022-11-15", "BUY",      "BHP.AX", "BHP Group",          "AU_EQUITY", Decimal("80"),  Decimal("46.15"),  "AUD", Decimal("19.95")),
    Tx("2023-01-20", "BUY",      "CSL.AX", "CSL Limited",        "AU_EQUITY", Decimal("10"),  Decimal("298.50"), "AUD", Decimal("19.95")),
    Tx("2023-06-01", "BUY",      "CBA.AX", "Commonwealth Bank",  "AU_EQUITY", Decimal("30"),  Decimal("97.80"),  "AUD", Decimal("19.95")),

    # CBA dividend — fully franked (30c in the dollar = 30% corporate tax paid)
    Tx("2023-09-20", "DIVIDEND",  "CBA.AX", "Commonwealth Bank", "AU_EQUITY", Decimal("80"),  Decimal("2.40"),   "AUD", Decimal("0"), Decimal("0.30")),
    Tx("2024-03-15", "DIVIDEND",  "CBA.AX", "Commonwealth Bank", "AU_EQUITY", Decimal("80"),  Decimal("2.55"),   "AUD", Decimal("0"), Decimal("0.30")),
    Tx("2023-11-30", "DIVIDEND",  "BHP.AX", "BHP Group",         "AU_EQUITY", Decimal("80"),  Decimal("1.30"),   "AUD", Decimal("0"), Decimal("0.30")),

    # Sell CBA parcel 1 (held > 12 months → CGT discount eligible)
    Tx("2024-08-15", "SELL",     "CBA.AX", "Commonwealth Bank",  "AU_EQUITY", Decimal("50"),  Decimal("132.60"), "AUD", Decimal("19.95")),

    # Sell BHP (held > 12 months → CGT discount eligible)
    Tx("2024-09-30", "SELL",     "BHP.AX", "BHP Group",          "AU_EQUITY", Decimal("80"),  Decimal("43.20"),  "AUD", Decimal("19.95")),

    # ── US stocks via Stake (USD, converted to AUD at RBA rate) ───────────────
    Tx("2023-03-05", "BUY",      "NVDA",  "NVIDIA Corporation",  "US_EQUITY", Decimal("20"),  Decimal("235.00"), "USD", Decimal("0")),
    Tx("2023-07-14", "BUY",      "TSLA",  "Tesla Inc",           "US_EQUITY", Decimal("15"),  Decimal("278.50"), "USD", Decimal("0")),
    Tx("2024-01-10", "BUY",      "NVDA",  "NVIDIA Corporation",  "US_EQUITY", Decimal("10"),  Decimal("495.00"), "USD", Decimal("0")),

    # Sell NVDA (first lot held > 12 months — discount eligible)
    Tx("2024-10-22", "SELL",     "NVDA",  "NVIDIA Corporation",  "US_EQUITY", Decimal("20"),  Decimal("136.00"), "USD", Decimal("0")),

    # Sell TSLA (held > 12 months — discount eligible, but at a LOSS)
    Tx("2025-02-10", "SELL",     "TSLA",  "Tesla Inc",           "US_EQUITY", Decimal("15"),  Decimal("292.40"), "USD", Decimal("0")),

    # ── Crypto via Kraken (USD) ───────────────────────────────────────────────
    Tx("2022-11-15", "BUY",      "BTC",   "Bitcoin",             "CRYPTO",    Decimal("0.5"), Decimal("16800.00"),"USD", Decimal("21.00")),
    Tx("2023-07-14", "BUY",      "ETH",   "Ethereum",            "CRYPTO",    Decimal("4.0"), Decimal("1920.00"), "USD", Decimal("7.68")),
    Tx("2024-02-28", "BUY",      "BTC",   "Bitcoin",             "CRYPTO",    Decimal("0.2"), Decimal("61500.00"),"USD", Decimal("61.50")),

    # Staking rewards — ETH on Kraken (assessable as ordinary income per ATO)
    Tx("2024-02-01", "STAKE_REWARD","ETH","Ethereum",            "CRYPTO",    Decimal("0.08"),Decimal("2920.00"), "USD", Decimal("0")),
    Tx("2024-05-01", "STAKE_REWARD","ETH","Ethereum",            "CRYPTO",    Decimal("0.06"),Decimal("3150.00"), "USD", Decimal("0")),

    # Sell BTC lot 1 (held > 12 months → CGT discount eligible — LARGE GAIN)
    Tx("2024-11-12", "SELL",     "BTC",   "Bitcoin",             "CRYPTO",    Decimal("0.5"), Decimal("88500.00"),"USD", Decimal("88.50")),

    # Sell ETH partial — held 16 months → discount eligible
    Tx("2025-01-15", "SELL",     "ETH",   "Ethereum",            "CRYPTO",    Decimal("2.0"), Decimal("3380.00"), "USD", Decimal("6.76")),
]


# ─────────────────────────────────────────────────────────────────────────────
# 4. FIFO LOT MATCHER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Lot:
    symbol: str
    name: str
    asset_class: str
    bought_date: str
    quantity: Decimal
    cost_basis_aud: Decimal      # total cost base for the lot in AUD
    remaining: Decimal = field(init=False)

    def __post_init__(self):
        self.remaining = self.quantity

    @property
    def cost_per_unit_aud(self) -> Decimal:
        return (self.cost_basis_aud / self.quantity).quantize(Decimal("0.000001"))


@dataclass
class CGTEvent:
    symbol: str
    name: str
    asset_class: str
    bought_date: str
    sold_date: str
    holding_days: int
    discount_eligible: bool
    quantity: Decimal
    cost_base_aud: Decimal
    proceeds_aud: Decimal

    @property
    def gross_gain_aud(self) -> Decimal:
        return (self.proceeds_aud - self.cost_base_aud).quantize(CENT)

    @property
    def is_loss(self) -> bool:
        return self.gross_gain_aud < ZERO


def build_lots_and_events(ledger: list[Tx]) -> tuple[list[CGTEvent], list[Lot], list[dict]]:
    """FIFO lot matching — returns (cgt_events, open_lots, income_events)."""
    open_lots: dict[str, list[Lot]] = {}
    cgt_events: list[CGTEvent] = []
    income_events: list[dict] = []

    for tx in sorted(ledger, key=lambda t: t.date):
        if tx.action == "BUY":
            lot = Lot(
                symbol=tx.symbol, name=tx.name, asset_class=tx.asset_class,
                bought_date=tx.date, quantity=tx.quantity,
                cost_basis_aud=tx.cost_basis_aud,
            )
            open_lots.setdefault(tx.symbol, []).append(lot)

        elif tx.action == "SELL":
            qty_to_sell = tx.quantity
            proceeds_per_unit = tx.proceeds_aud / tx.quantity
            lots = open_lots.get(tx.symbol, [])
            for lot in lots:
                if qty_to_sell <= ZERO:
                    break
                if lot.remaining <= ZERO:
                    continue
                matched = min(lot.remaining, qty_to_sell)
                lot_cost = (matched * lot.cost_per_unit_aud).quantize(CENT)
                lot_proceeds = (matched * proceeds_per_unit).quantize(CENT)
                sold_dt = dt(tx.date)
                bought_dt = dt(lot.bought_date)
                days = (sold_dt - bought_dt).days
                cgt_events.append(CGTEvent(
                    symbol=tx.symbol, name=tx.name, asset_class=tx.asset_class,
                    bought_date=lot.bought_date, sold_date=tx.date,
                    holding_days=days, discount_eligible=(days >= 365),
                    quantity=matched,
                    cost_base_aud=lot_cost,
                    proceeds_aud=lot_proceeds,
                ))
                lot.remaining -= matched
                qty_to_sell -= matched

        elif tx.action == "DIVIDEND":
            gross_aud = (tx.quantity * tx.price).quantize(CENT)
            # Franking credit = gross * franking_rate / (1 - corporate_tax_rate)
            # Simplified: franking_credit = gross * franking_rate * 30/70
            fc = ZERO
            if tx.franking_rate:
                # gross dividend is already the cash amount; grossed-up includes franking
                fc = (gross_aud * tx.franking_rate / (1 - tx.franking_rate)).quantize(CENT)
            income_events.append({
                "type": "DIVIDEND", "symbol": tx.symbol, "date": tx.date,
                "amount_aud": gross_aud, "franking_credit_aud": fc,
            })

        elif tx.action == "STAKE_REWARD":
            income_aud = (tx.quantity * tx.price * get_aud_rate(tx.currency, tx.date)).quantize(CENT)
            income_events.append({
                "type": "STAKE_REWARD", "symbol": tx.symbol, "date": tx.date,
                "amount_aud": income_aud, "franking_credit_aud": ZERO,
            })

    # Collect remaining open lots
    remaining_lots = [lot for lots in open_lots.values() for lot in lots if lot.remaining > ZERO]
    return cgt_events, remaining_lots, income_events


# ─────────────────────────────────────────────────────────────────────────────
# 5. ATO CGT REPORT COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

FY_START = "2024-07-01"
FY_END   = "2025-06-30"
FY_LABEL = "FY2024-25"


def compute_ato_report(
    cgt_events: list[CGTEvent],
    income_events: list[dict],
    other_income_aud: Decimal = Decimal("95000"),
    cgt_discount_rate: Decimal = Decimal("0.50"),
) -> dict:
    """Mirror of ATOTaxEngine.compute_ato_report() using in-memory data."""

    # Filter to FY2024-25 disposals
    fy_events = [e for e in cgt_events if FY_START <= e.sold_date <= FY_END]

    gains    = [e for e in fy_events if not e.is_loss]
    losses   = [e for e in fy_events if e.is_loss]

    gross_gains_total = sum(e.gross_gain_aud for e in gains)
    total_losses      = sum(abs(e.gross_gain_aud) for e in losses)

    non_discount_gains    = sum(e.gross_gain_aud for e in gains if not e.discount_eligible)
    discount_eligible_gains = sum(e.gross_gain_aud for e in gains if e.discount_eligible)

    # Apply losses: non-discount first, then discount (s102-5)
    available_losses = total_losses

    loss_vs_non_disc = min(available_losses, non_discount_gains)
    net_non_discount = max(ZERO, non_discount_gains - loss_vs_non_disc)
    available_losses -= loss_vs_non_disc

    loss_vs_disc = min(available_losses, discount_eligible_gains)
    net_disc_before = max(ZERO, discount_eligible_gains - loss_vs_disc)
    available_losses -= loss_vs_disc

    discount_amount  = (net_disc_before * cgt_discount_rate).quantize(CENT)
    net_disc_after   = net_disc_before - discount_amount
    net_capital_gain = net_non_discount + net_disc_after
    losses_cf        = available_losses  # unused losses carried forward

    # Income for FY2024-25
    fy_income = [e for e in income_events if FY_START <= e["date"] <= FY_END]
    div_income    = sum(e["amount_aud"] for e in fy_income if e["type"] == "DIVIDEND")
    franking_cred = sum(e["franking_credit_aud"] for e in fy_income)
    staking_income= sum(e["amount_aud"] for e in fy_income if e["type"] == "STAKE_REWARD")

    # Tax estimates
    total_income = other_income_aud + div_income + staking_income + net_capital_gain
    tax_without_cgt = ato_income_tax(other_income_aud + div_income + staking_income)
    tax_with_cgt    = ato_income_tax(total_income)
    cgt_tax = max(ZERO, tax_with_cgt - tax_without_cgt)
    eff_rate = (cgt_tax / net_capital_gain * 100).quantize(CENT) if net_capital_gain > ZERO else ZERO

    return {
        "fy_label": FY_LABEL,
        "fy_events": fy_events,
        "gains": gains, "losses": losses,
        "gross_capital_gains_aud": gross_gains_total,
        "capital_losses_aud": total_losses,
        "non_discount_gains_aud": non_discount_gains,
        "discount_eligible_gains_aud": discount_eligible_gains,
        "losses_applied_to_non_discount": loss_vs_non_disc,
        "losses_applied_to_discount": loss_vs_disc,
        "net_gain_non_discount_aud": net_non_discount,
        "net_gain_disc_before_reduction": net_disc_before,
        "cgt_discount_applied_aud": discount_amount,
        "net_capital_gain_aud": net_capital_gain,
        "losses_carried_forward_aud": losses_cf,
        "dividend_income_aud": div_income,
        "franking_credits_aud": franking_cred,
        "staking_income_aud": staking_income,
        "other_income_aud": other_income_aud,
        "total_taxable_income_aud": total_income,
        "tax_without_cgt_aud": tax_without_cgt,
        "tax_with_cgt_aud": tax_with_cgt,
        "estimated_cgt_tax_aud": cgt_tax,
        "effective_cgt_rate_pct": eff_rate,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. BANK IMPORT DEMO (CBA and Wise CSVs)
# ─────────────────────────────────────────────────────────────────────────────

CBA_CSV = """\
Date,Description,Debit,Credit,Balance
01/07/2024,Opening balance,,,42318.50
15/07/2024,BPAY - AESOP FINANCIAL,,,-
28/07/2024,PAYROLL - MAPLE TECH PTY LTD,,6250.00,48568.50
05/08/2024,COMMBROKER BROKERAGE FEE,19.95,,48548.55
12/08/2024,TRANSFER TO SAVINGS,5000.00,,43548.55
20/08/2024,SPLIT - SYD WATER,189.40,,43359.15
05/09/2024,COMMBROKER BROKERAGE FEE,19.95,,43339.20
30/09/2024,PAYROLL - MAPLE TECH PTY LTD,,6250.00,49589.20
15/10/2024,COINSPOT PURCHASE,2500.00,,47089.20
22/10/2024,PAYPAL TRANSFER,350.00,,46739.20
01/11/2024,AIRBNB REFUND,,120.00,46859.20
30/11/2024,PAYROLL - MAPLE TECH PTY LTD,,6250.00,53109.20
"""

WISE_CSV = """\
TransferWise ID,Date,Amount,Currency,Description,Payment Reference,Running Balance
T240715001,2024-07-15,-1500.00,AUD,Transfer to USD account,Stake deposit,40818.50
T240715002,2024-07-15,985.72,USD,Received transfer,Stake deposit,985.72
T241001001,2024-10-01,-800.00,AUD,Transfer to EUR,,40018.50
T241001002,2024-10-01,480.55,EUR,Received transfer,,480.55
T250115001,2025-01-15,3250.00,AUD,Received from Stake,ETH sale proceeds,43268.50
"""


def parse_cba(csv_text: str) -> list[dict]:
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        date_raw = row.get("Date", "").strip()
        if not date_raw:
            continue
        try:
            date_obj = datetime.strptime(date_raw, "%d/%m/%Y")
            date_iso = date_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue

        debit = row.get("Debit", "").strip()
        credit = row.get("Credit", "").strip()
        desc = row.get("Description", "").strip()

        try:
            amount = -Decimal(debit) if debit else Decimal(credit) if credit else ZERO
        except InvalidOperation:
            continue

        import_hash = hashlib.sha256(f"cba|{date_iso}|{desc}|{amount}".encode()).hexdigest()[:12]
        rows.append({
            "institution": "CBA", "date": date_iso, "description": desc,
            "amount": amount, "currency": "AUD", "amount_aud": amount,
            "fx_rate": Decimal("1.0"), "import_hash": import_hash,
        })
    return rows


def parse_wise(csv_text: str) -> list[dict]:
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        date_raw = row.get("Date", "").strip()
        try:
            date_iso = datetime.strptime(date_raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            continue

        amount_raw = row.get("Amount", "").strip()
        currency = row.get("Currency", "AUD").strip().upper()
        desc = row.get("Description", "").strip()

        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            continue

        fx_rate = get_aud_rate(currency, date_iso)
        amount_aud = (amount * fx_rate).quantize(CENT)
        import_hash = hashlib.sha256(f"wise|{date_iso}|{desc}|{amount}|{currency}".encode()).hexdigest()[:12]
        rows.append({
            "institution": "Wise", "date": date_iso, "description": desc,
            "amount": amount, "currency": currency,
            "amount_aud": amount_aud, "fx_rate": fx_rate,
            "import_hash": import_hash,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# 7. DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

W = 72

def rule(char="─"):
    print(DIM + char * W + RESET)

def header(title: str, color=CYAN):
    print()
    print(color + BOLD + "  " + title + RESET)
    rule()

def row(label: str, value: str, color=None, indent=2):
    gap = W - indent - len(label) - len(value) - 2
    col = color or RESET
    print(" " * indent + label + " " * max(1, gap) + col + value + RESET)

def gain_color(v: Decimal) -> str:
    return GREEN if v >= ZERO else RED


# ─────────────────────────────────────────────────────────────────────────────
# 8. MAIN OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # ── Build ledger ──────────────────────────────────────────────────────────
    cgt_events, open_lots, income_events = build_lots_and_events(LEDGER)

    # ── Compute ATO report ────────────────────────────────────────────────────
    OTHER_INCOME = Decimal("95000")  # salary
    rpt = compute_ato_report(cgt_events, income_events, OTHER_INCOME)

    # ── Parse bank CSVs ───────────────────────────────────────────────────────
    cba_rows  = parse_cba(CBA_CSV)
    wise_rows = parse_wise(WISE_CSV)

    # ─────────────────────────────────────────────────────────────────────────
    # BANNER
    # ─────────────────────────────────────────────────────────────────────────
    print()
    print(CYAN + BOLD + "=" * W)
    print(f"  InvestIQ — ATO CGT Report Demo".center(W))
    print(f"  {FY_LABEL} (1 July 2024 – 30 June 2025)".center(W))
    print("=" * W + RESET)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 1: TRANSACTION LEDGER SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    header("TRANSACTION LEDGER  (sample investor — CommSec + Stake + Kraken)")

    print(f"\n  {'Date':<12} {'Sym':<8} {'Action':<14} {'Qty':>8} {'Price':>12} {'Ccy':<4} {'AUD Value':>14}")
    rule("·")
    for tx in sorted(LEDGER, key=lambda t: t.date):
        if tx.action in ("BUY", "SELL"):
            aud_val = tx.cost_basis_aud if tx.action == "BUY" else tx.proceeds_aud
            col = GREEN if tx.action == "BUY" else YELLOW
            print(f"  {tx.date:<12} {tx.symbol:<8} {col}{tx.action:<14}{RESET} "
                  f"{float(tx.quantity):>8.4f} {float(tx.price):>12,.2f} {tx.currency:<4} "
                  f"{aud(aud_val):>14}")
        elif tx.action == "DIVIDEND":
            gross = (tx.quantity * tx.price).quantize(CENT)
            print(f"  {tx.date:<12} {tx.symbol:<8} {BLUE}{'DIVIDEND':<14}{RESET} "
                  f"{'':>8} {'':>12} {'AUD':<4} {aud(gross):>14}")
        elif tx.action == "STAKE_REWARD":
            aud_val = (tx.quantity * tx.price * get_aud_rate(tx.currency, tx.date)).quantize(CENT)
            print(f"  {tx.date:<12} {tx.symbol:<8} {BLUE}{'STAKE_REWARD':<14}{RESET} "
                  f"{float(tx.quantity):>8.4f} {'':>12} {tx.currency:<4} {aud(aud_val):>14}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 2: CGT EVENTS (FY2024-25 disposals)
    # ─────────────────────────────────────────────────────────────────────────
    header("CGT EVENTS  (FY2024-25 disposals — FIFO lot matching)")

    print(f"\n  {'Symbol':<8} {'Acquired':<12} {'Sold':<12} {'Days':>5} {'Disc?':<6} "
          f"{'Cost Base':>13} {'Proceeds':>13} {'Gain/Loss':>13}")
    rule("·")

    for e in rpt["fy_events"]:
        col = gain_color(e.gross_gain_aud)
        disc = GREEN + "Yes✓" + RESET if e.discount_eligible else DIM + "No" + RESET
        gain_str = col + aud(e.gross_gain_aud) + RESET
        print(f"  {e.symbol:<8} {e.bought_date:<12} {e.sold_date:<12} {e.holding_days:>5} "
              f"  {disc:<14} {aud(e.cost_base_aud):>13} {aud(e.proceeds_aud):>13} {gain_str:>13}")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: ATO CGT CALCULATION WATERFALL
    # ─────────────────────────────────────────────────────────────────────────
    header("ATO CGT CALCULATION  (ITAA 1997 — Schedule 3 / Item 18)")

    print()
    row("Gross capital gains (all disposals)          [18A]",
        aud(rpt["gross_capital_gains_aud"]), YELLOW)
    print()
    row("  Short-held gains (held < 12 months)",
        aud(rpt["non_discount_gains_aud"]))
    row("  Long-held gains  (held ≥ 12 months, pre-discount)",
        aud(rpt["discount_eligible_gains_aud"]))
    print()
    row("Capital losses (current year)                [18B]",
        "-" + aud(rpt["capital_losses_aud"]) if rpt["capital_losses_aud"] else aud(ZERO), RED)
    print()
    rule("·")
    row("  Losses applied to short-held gains (s102-5 order)",
        "-" + aud(rpt["losses_applied_to_non_discount"]), RED)
    row("  Net short-held gains after losses",
        aud(rpt["net_gain_non_discount_aud"]))
    print()
    row("  Losses applied to long-held gains (remaining)",
        "-" + aud(rpt["losses_applied_to_discount"]), RED)
    row("  Net long-held gains after losses",
        aud(rpt["net_gain_disc_before_reduction"]))
    row("  50% CGT discount applied (Div 115, individual)",
        "-" + aud(rpt["cgt_discount_applied_aud"]), GREEN)
    row("  Net long-held gains after 50% discount",
        aud(rpt["net_gain_disc_before_reduction"] - rpt["cgt_discount_applied_aud"]))
    print()
    rule()
    row(f"NET CAPITAL GAIN                             [18H]",
        aud(rpt["net_capital_gain_aud"]),
        GREEN if rpt["net_capital_gain_aud"] >= ZERO else RED)
    row("Capital losses carried forward               [18V]",
        aud(rpt["losses_carried_forward_aud"]),
        BLUE if rpt["losses_carried_forward_aud"] > ZERO else None)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: INVESTMENT INCOME
    # ─────────────────────────────────────────────────────────────────────────
    header("INVESTMENT INCOME  (FY2024-25)")

    print()
    row("Dividends received (AUD)",           aud(rpt["dividend_income_aud"]))
    row("Franking credits (reduce tax payable)", aud(rpt["franking_credits_aud"]), BLUE)
    row("Staking / crypto rewards (AUD)",     aud(rpt["staking_income_aud"]))
    row("Interest income (AUD)",              aud(ZERO))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5: TAX ESTIMATE
    # ─────────────────────────────────────────────────────────────────────────
    header("TAX ESTIMATE  (2024-25 marginal rates + Medicare Levy + LITO)")

    print()
    row("Salary / other income",              aud(rpt["other_income_aud"]))
    row("Dividend income",                    aud(rpt["dividend_income_aud"]))
    row("Staking income",                     aud(rpt["staking_income_aud"]))
    row("Net capital gain                     [18H]",
        aud(rpt["net_capital_gain_aud"]))
    rule("·")
    row("Total assessable income",            aud(rpt["total_taxable_income_aud"]), YELLOW)
    print()
    row("Tax without CGT (salary + div + staking)", aud(rpt["tax_without_cgt_aud"]))
    row("Tax with CGT included",              aud(rpt["tax_with_cgt_aud"]))
    rule("·")
    row("Tax attributable to CGT",            aud(rpt["estimated_cgt_tax_aud"]), RED)
    row("Franking credits offset",            "-" + aud(rpt["franking_credits_aud"]), GREEN)
    net_tax = rpt["tax_with_cgt_aud"] - rpt["franking_credits_aud"]
    rule()
    row("ESTIMATED NET TAX PAYABLE",          aud(net_tax), YELLOW + BOLD)
    row("Effective CGT rate",                 pct(rpt["effective_cgt_rate_pct"]))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6: myTax ENTRY CHEAT SHEET
    # ─────────────────────────────────────────────────────────────────────────
    header("myTax ENTRY GUIDE  (what to enter in your tax return)", YELLOW)

    print()
    entries = [
        ("Item 18A — Gross capital gains",    aud(rpt["gross_capital_gains_aud"])),
        ("Item 18B — Capital losses (this year)", aud(rpt["capital_losses_aud"])),
        ("Item 18H — Net capital gain",       aud(rpt["net_capital_gain_aud"])),
        ("Item 18V — Losses carried forward", aud(rpt["losses_carried_forward_aud"])),
        ("Item 11  — Dividend income",        aud(rpt["dividend_income_aud"])),
        ("Item 11  — Franking credits",       aud(rpt["franking_credits_aud"])),
    ]
    for label, value in entries:
        row(label, value, CYAN)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 7: OPEN POSITIONS (unrealised)
    # ─────────────────────────────────────────────────────────────────────────
    header("OPEN POSITIONS  (unrealised — carry into FY2025-26)")

    print(f"\n  {'Symbol':<8} {'Bought':<12} {'Qty Rem':>9} {'Cost/Unit (AUD)':>16} {'Total Cost (AUD)':>17}")
    rule("·")
    total_open_cost = ZERO
    for lot in sorted(open_lots, key=lambda l: l.symbol):
        print(f"  {lot.symbol:<8} {lot.bought_date:<12} {float(lot.remaining):>9.4f} "
              f"{aud(lot.cost_per_unit_aud):>16} {aud(lot.remaining * lot.cost_per_unit_aud):>17}")
        total_open_cost += lot.remaining * lot.cost_per_unit_aud
    rule("·")
    row("Total cost base (open positions)", aud(total_open_cost.quantize(CENT)))

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 8: BANK IMPORT DEMO
    # ─────────────────────────────────────────────────────────────────────────
    header("BANK IMPORT DEMO  (auto-parsed CSV statements)")

    print(f"\n  {BOLD}Commonwealth Bank (CBA) — CommBank NetBank export{RESET}")
    print(f"  {'Date':<12} {'Description':<35} {'Amount':>10} {'Hash':>14}")
    rule("·")
    for r in cba_rows:
        col = GREEN if r["amount"] >= ZERO else RED
        print(f"  {r['date']:<12} {r['description'][:34]:<35} "
              f"{col}{float(r['amount']):>+10.2f}{RESET}  {DIM}{r['import_hash']}{RESET}")

    print(f"\n  {BOLD}Wise (TransferWise) — multi-currency statement{RESET}")
    print(f"  {'Date':<12} {'Description':<28} {'Amount':>10} {'Ccy':<4} {'AUD':>10} {'FX Rate':>8}")
    rule("·")
    for r in wise_rows:
        col = GREEN if r["amount"] >= ZERO else RED
        print(f"  {r['date']:<12} {r['description'][:27]:<28} "
              f"{col}{float(r['amount']):>+10.2f}{RESET} {r['currency']:<4} "
              f"{aud(r['amount_aud']):>10} {float(r['fx_rate']):>8.4f}")

    print(f"\n  {DIM}Each row is hashed (SHA-256) for deduplication on re-import.{RESET}")
    print(f"  {DIM}Non-AUD amounts auto-converted using RBA daily rates.{RESET}")

    # ─────────────────────────────────────────────────────────────────────────
    # FOOTER
    # ─────────────────────────────────────────────────────────────────────────
    print()
    print(CYAN + "─" * W)
    print(f"  {DIM}This demo mirrors the output of:{RESET}")
    print(f"    GET /api/v1/tax/ato/summary?fy=2025&method=FIFO")
    print(f"    POST /api/bank-import/upload  (CBA + Wise)")
    print(f"  {DIM}All calculations use 2024-25 ATO marginal rates (ITAA 1997){RESET}")
    print(f"  {DIM}Exchange rates: RBA daily (ATO-authoritative source){RESET}")
    print(f"  {YELLOW}Not tax advice. Consult a registered tax agent.{RESET}")
    print(CYAN + "─" * W + RESET)
    print()


if __name__ == "__main__":
    main()
