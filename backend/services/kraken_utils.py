"""Kraken-specific parsing helpers."""
from decimal import Decimal

ZERO = Decimal("0")


def detect_ledger_conversion_refs(
    ledger: list[tuple[str, dict]],
    trade_base_symbols: dict[str, str],
    normalize_asset,
    fiat_symbols: set[str],
    stablecoin_symbols: set[str],
) -> dict[str, dict[str, tuple[str, Decimal | None]]]:
    """
    Detect Kraken Convert rows that only appear in ledger data.

    Returns refid -> symbol -> (BUY|SELL, price_per_unit).
    """
    grouped: dict[str, list[dict]] = {}
    for _, entry in ledger:
        ref_id = entry.get("refid", "")
        if not ref_id or ref_id in trade_base_symbols:
            continue
        symbol = normalize_asset(entry.get("asset", ""))
        if symbol in fiat_symbols:
            continue
        amount = Decimal(str(entry.get("amount", 0)))
        if amount == ZERO:
            continue
        grouped.setdefault(ref_id, []).append({"symbol": symbol, "amount": amount})

    detected: dict[str, dict[str, tuple[str, Decimal | None]]] = {}
    for ref_id, entries in grouped.items():
        positives = [entry for entry in entries if entry["amount"] > ZERO]
        negatives = [entry for entry in entries if entry["amount"] < ZERO]
        if not positives or not negatives:
            continue

        spent_stable_value = sum(
            abs(entry["amount"])
            for entry in negatives
            if entry["symbol"] in stablecoin_symbols
        )
        received_stable_value = sum(
            entry["amount"]
            for entry in positives
            if entry["symbol"] in stablecoin_symbols
        )
        quote_value = spent_stable_value or received_stable_value

        detected[ref_id] = {}
        for entry in positives:
            symbol = entry["symbol"]
            price = Decimal("1.0") if symbol in stablecoin_symbols else None
            if quote_value > ZERO and symbol not in stablecoin_symbols and entry["amount"] > ZERO:
                price = (quote_value / entry["amount"]).quantize(Decimal("0.0000000001"))
            detected[ref_id][symbol] = ("BUY", price)

        for entry in negatives:
            symbol = entry["symbol"]
            price = Decimal("1.0") if symbol in stablecoin_symbols else None
            if quote_value > ZERO and symbol not in stablecoin_symbols and abs(entry["amount"]) > ZERO:
                price = (quote_value / abs(entry["amount"])).quantize(Decimal("0.0000000001"))
            detected[ref_id][symbol] = ("SELL", price)

    return detected
