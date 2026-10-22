import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from services.ato_tax_engine import (
    ATOTaxEngine,
    CGTEvent,
    basic_income_tax,
    calculate_tax,
    cgt_discount_eligible,
    low_income_tax_offset,
    rules_for_fy,
)


def test_2024_25_stage_three_rates_are_used():
    rules = rules_for_fy(2025)
    assert basic_income_tax(Decimal("80000"), rules) == Decimal("14788.00")


def test_2026_27_first_rate_is_fifteen_percent():
    rules = rules_for_fy(2027)
    assert basic_income_tax(Decimal("45000"), rules) == Decimal("4020.00")


def test_lito_has_both_taper_bands():
    assert low_income_tax_offset(Decimal("37500")) == Decimal("700")
    assert low_income_tax_offset(Decimal("45000")) == Decimal("325")
    assert low_income_tax_offset(Decimal("66667")) == Decimal("0")


def test_franking_credit_is_refundable_offset_not_income_deduction():
    rules = rules_for_fy(2025)
    # $700 cash dividend + $300 credit is $1,000 assessable; the $300 is then
    # applied as a refundable tax offset.
    result = calculate_tax(Decimal("81000"), rules, franking_offsets=Decimal("300"))
    assert result.taxable_income == Decimal("81000.00")
    assert result.refundable_offsets == Decimal("300.00")
    assert result.tax_after_offsets < result.basic_tax + result.medicare_levy


def test_discount_requires_disposal_after_first_anniversary():
    acquired = datetime(2023, 7, 1, tzinfo=timezone.utc)
    assert not cgt_discount_eligible(acquired, datetime(2024, 7, 1, tzinfo=timezone.utc))
    assert cgt_discount_eligible(acquired, datetime(2024, 7, 2, tzinfo=timezone.utc))


def _event(gain: str, discount: bool) -> CGTEvent:
    acquired = datetime(2023, 1, 1, tzinfo=timezone.utc)
    disposed = datetime(2025, 1, 2, tzinfo=timezone.utc)
    value = Decimal(gain)
    return CGTEvent(
        "ABC", "ABC", "EQUITY", "Broker", acquired, disposed, 732,
        discount, Decimal("1"), Decimal("100"), Decimal("100") + value,
        value, max(Decimal("0"), -value),
    )


def test_losses_are_applied_to_non_discount_gain_first():
    engine = object.__new__(ATOTaxEngine)
    result = engine._aggregate_cgt(
        [_event("1000", False), _event("1000", True), _event("-600", False)],
        {},
        rules_for_fy(2025),
    )
    assert result["losses_applied"] == Decimal("600.00")
    assert result["discount_before"] == Decimal("1000.00")
    assert result["discount"] == Decimal("500.00")
    assert result["net_gain"] == Decimal("900.00")


def test_excess_losses_carry_forward_and_do_not_create_negative_income():
    engine = object.__new__(ATOTaxEngine)
    result = engine._aggregate_cgt(
        [_event("250", False), _event("-1000", False)],
        {"prior_year_capital_losses_aud": 100},
        rules_for_fy(2025),
    )
    assert result["net_gain"] == Decimal("0.00")
    assert result["losses_cf"] == Decimal("850.00")


def test_report_is_built_from_transactions_without_tax_lot_rows():
    asset = SimpleNamespace(id="asset-1", symbol="ABC", name="ABC Ltd", asset_class="EQUITY", country="AU", currency="AUD")
    account = SimpleNamespace(id="account-1", name="Broker")

    def transaction(txn_id, kind, when, qty=None, net_aud=None, **extra):
        values = dict(
            id=txn_id, account_id=account.id, transaction_type=kind,
            transacted_at=when, quantity=qty, net_amount_aud=net_aud,
            net_amount=None, price_per_unit_aud=None, price_per_unit=None,
            fees=Decimal("0"), fx_rate_to_aud=Decimal("1"), currency="AUD",
            gross_amount=None, tax_withheld=None, franking_credit=None,
            franking_pct=None, raw_data=None,
        )
        values.update(extra)
        return SimpleNamespace(**values)

    rows = [
        (transaction("buy", "BUY", datetime(2023, 7, 1, tzinfo=timezone.utc), Decimal("100"), Decimal("-1000")), asset, account),
        (transaction("sell", "SELL", datetime(2024, 8, 1, tzinfo=timezone.utc), Decimal("100"), Decimal("2000")), asset, account),
        (transaction("div", "DIVIDEND", datetime(2025, 3, 1, tzinfo=timezone.utc), net_aud=Decimal("700"),
                     franking_credit=Decimal("300"), franking_pct=Decimal("100")), asset, account),
    ]

    class Result:
        def all(self):
            return rows

    class DB:
        async def execute(self, _query):
            return Result()

    class FX:
        async def get_aud_rate(self, *_args):
            return Decimal("1")

        async def close(self):
            pass

    report = asyncio.run(ATOTaxEngine(DB(), FX()).compute_ato_report(
        "user", 2025, "FIFO", {"other_income_aud": 80000}
    ))
    assert len(report.cgt_events) == 1
    assert report.gross_capital_gains_aud == Decimal("1000.00")
    assert report.cgt_discount_applied == Decimal("500.00")
    assert report.net_capital_gain_aud == Decimal("500.00")
    assert report.franked_dividends_aud == Decimal("700.00")
    assert report.franking_credits_aud == Decimal("300.00")
    assert report.assessable_dividend_income_aud == Decimal("1000.00")


def test_foreign_dividend_uses_explicit_gross_amount_not_stored_net_aud():
    engine = object.__new__(ATOTaxEngine)

    class FX:
        async def get_aud_rate(self, currency, *_args):
            return Decimal("1.5") if currency == "USD" else Decimal("1")

    engine.fx = FX()
    txn = SimpleNamespace(
        transaction_type="DIVIDEND",
        transacted_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        gross_amount=Decimal("120"),
        net_amount=Decimal("100"),
        net_amount_aud=Decimal("150"),
        net_amount_usd=None,
        tax_withheld=Decimal("20"),
        currency="USD",
        fx_rate_to_aud=Decimal("1.5"),
        quantity=None,
        dividend_per_share=None,
        price_per_unit=None,
        franking_credit=None,
        franking_pct=None,
        raw_data=None,
    )
    asset = SimpleNamespace(symbol="ABC", country="US", currency="USD")
    account = SimpleNamespace(name="Broker")

    income, warnings = asyncio.run(engine._income(
        [(txn, asset, account)],
        datetime(2025, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
        {},
    ))

    assert warnings == []
    assert income.foreign_dividends == Decimal("180.00")
    assert income.foreign_tax_paid == Decimal("30.00")
