#!/usr/bin/env python3
"""
Seed script: creates a demo user, accounts, and sample transactions via the API.
Run: python3 scripts/seed_sample_data.py
"""
import json
import sys
import urllib.request
import urllib.error

API = "http://localhost:8000/api/v1"
EMAIL = "demo@investiq.com.au"
PASSWORD = "demo1234"
FULL_NAME = "Demo Investor"


def api(method, path, data=None, token=None):
    url = f"{API}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        if e.code == 409:
            return None  # already exists
        print(f"  API error {e.code}: {detail}")
        return None


def main():
    print("=== InvestIQ Sample Data Seed ===\n")

    # 1) Register or login
    print(f"1. Creating user {EMAIL}...")
    resp = api("POST", "/auth/register", {
        "email": EMAIL, "password": PASSWORD, "full_name": FULL_NAME,
        "preferred_currency": "AUD",
    })
    if resp and "access_token" in resp:
        token = resp["access_token"]
        print(f"   Registered OK (user_id={resp['user_id']})")
    else:
        print("   Already exists, logging in...")
        resp = api("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
        if not resp or "access_token" not in resp:
            print("   FAILED to login. Check backend.")
            sys.exit(1)
        token = resp["access_token"]
        print(f"   Logged in OK (user_id={resp['user_id']})")

    # 2) Create accounts
    print("\n2. Creating accounts...")
    accounts = {}
    account_defs = [
        {"name": "CommSec — ASX", "institution_name": "CommSec", "account_type": "BROKERAGE", "currency": "AUD"},
        {"name": "Stake — US Equities", "institution_name": "Stake", "account_type": "BROKERAGE", "currency": "USD"},
        {"name": "Kraken — Crypto", "institution_name": "Kraken", "account_type": "CRYPTO_EXCHANGE", "currency": "USD"},
        {"name": "CMC Invest", "institution_name": "CMC Markets", "account_type": "BROKERAGE", "currency": "AUD"},
    ]
    for acct in account_defs:
        r = api("POST", "/portfolio/accounts", acct, token)
        if r and "id" in r:
            accounts[acct["name"]] = r["id"]
            print(f"   Created: {acct['name']} -> {r['id'][:8]}...")
        else:
            # Might already exist; fetch all
            pass

    # If accounts dict is incomplete, fetch from API
    if len(accounts) < len(account_defs):
        all_accts = api("GET", "/portfolio/accounts", token=token)
        if all_accts:
            for a in all_accts:
                accounts[a["name"]] = a["id"]
            print(f"   Fetched {len(all_accts)} accounts total")

    if not accounts:
        print("   ERROR: No accounts available")
        sys.exit(1)

    # 3) Create sample transactions
    print("\n3. Creating sample transactions...")

    # Pick first available account IDs
    asx_id = accounts.get("CommSec — ASX") or list(accounts.values())[0]
    us_id = accounts.get("Stake — US Equities") or asx_id
    crypto_id = accounts.get("Kraken — Crypto") or asx_id

    sample_transactions = [
        # ASX trades (AUD)
        {"account_id": asx_id, "asset_symbol": "CBA", "transaction_type": "BUY", "quantity": 50, "price_per_unit": 98.50, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-02-15T10:30:00Z", "notes": "CommSec buy"},
        {"account_id": asx_id, "asset_symbol": "BHP", "transaction_type": "BUY", "quantity": 100, "price_per_unit": 45.20, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-03-01T09:15:00Z"},
        {"account_id": asx_id, "asset_symbol": "CSL", "transaction_type": "BUY", "quantity": 20, "price_per_unit": 285.00, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-03-15T11:00:00Z"},
        {"account_id": asx_id, "asset_symbol": "WES", "transaction_type": "BUY", "quantity": 30, "price_per_unit": 62.50, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-04-10T14:20:00Z"},
        {"account_id": asx_id, "asset_symbol": "NAB", "transaction_type": "BUY", "quantity": 150, "price_per_unit": 33.80, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-05-20T10:00:00Z"},
        {"account_id": asx_id, "asset_symbol": "RIO", "transaction_type": "BUY", "quantity": 40, "price_per_unit": 118.50, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-06-01T09:30:00Z"},
        {"account_id": asx_id, "asset_symbol": "BHP", "transaction_type": "SELL", "quantity": 50, "price_per_unit": 48.90, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-09-15T13:45:00Z", "notes": "Partial sell"},
        {"account_id": asx_id, "asset_symbol": "CBA", "transaction_type": "DIVIDEND", "quantity": 50, "price_per_unit": 0, "fees": 0, "currency": "AUD", "transacted_at": "2024-09-20T00:00:00Z", "notes": "CBA interim dividend $2.15/share"},
        {"account_id": asx_id, "asset_symbol": "NAB", "transaction_type": "DIVIDEND", "quantity": 150, "price_per_unit": 0, "fees": 0, "currency": "AUD", "transacted_at": "2024-11-15T00:00:00Z", "notes": "NAB final dividend $0.84/share"},
        {"account_id": asx_id, "asset_symbol": "FMG", "transaction_type": "BUY", "quantity": 80, "price_per_unit": 20.15, "fees": 19.95, "currency": "AUD", "transacted_at": "2024-11-20T10:30:00Z"},
        {"account_id": asx_id, "asset_symbol": "WES", "transaction_type": "SELL", "quantity": 30, "price_per_unit": 71.20, "fees": 19.95, "currency": "AUD", "transacted_at": "2025-01-10T11:00:00Z"},
        {"account_id": asx_id, "asset_symbol": "TLS", "transaction_type": "BUY", "quantity": 500, "price_per_unit": 3.95, "fees": 19.95, "currency": "AUD", "transacted_at": "2025-02-05T09:45:00Z"},

        # US equities (USD via Stake)
        {"account_id": us_id, "asset_symbol": "AAPL", "transaction_type": "BUY", "quantity": 15, "price_per_unit": 178.50, "fees": 0, "currency": "USD", "transacted_at": "2024-01-20T15:30:00Z"},
        {"account_id": us_id, "asset_symbol": "NVDA", "transaction_type": "BUY", "quantity": 10, "price_per_unit": 550.00, "fees": 0, "currency": "USD", "transacted_at": "2024-02-10T16:00:00Z"},
        {"account_id": us_id, "asset_symbol": "MSFT", "transaction_type": "BUY", "quantity": 8, "price_per_unit": 405.00, "fees": 0, "currency": "USD", "transacted_at": "2024-04-05T14:30:00Z"},
        {"account_id": us_id, "asset_symbol": "GOOGL", "transaction_type": "BUY", "quantity": 20, "price_per_unit": 155.00, "fees": 0, "currency": "USD", "transacted_at": "2024-05-15T15:00:00Z"},
        {"account_id": us_id, "asset_symbol": "NVDA", "transaction_type": "SELL", "quantity": 5, "price_per_unit": 880.00, "fees": 0, "currency": "USD", "transacted_at": "2024-08-20T16:30:00Z", "notes": "Partial profit take"},
        {"account_id": us_id, "asset_symbol": "AAPL", "transaction_type": "DIVIDEND", "quantity": 15, "price_per_unit": 0, "fees": 0, "currency": "USD", "transacted_at": "2024-08-15T00:00:00Z", "notes": "AAPL quarterly dividend"},
        {"account_id": us_id, "asset_symbol": "TSLA", "transaction_type": "BUY", "quantity": 12, "price_per_unit": 245.00, "fees": 0, "currency": "USD", "transacted_at": "2024-10-01T15:30:00Z"},
        {"account_id": us_id, "asset_symbol": "AMZN", "transaction_type": "BUY", "quantity": 18, "price_per_unit": 185.00, "fees": 0, "currency": "USD", "transacted_at": "2025-01-15T14:30:00Z"},

        # Crypto (Kraken)
        {"account_id": crypto_id, "asset_symbol": "BTC", "transaction_type": "BUY", "quantity": 0.15, "price_per_unit": 42500.00, "fees": 12.50, "currency": "USD", "transacted_at": "2024-01-10T08:00:00Z"},
        {"account_id": crypto_id, "asset_symbol": "ETH", "transaction_type": "BUY", "quantity": 2.5, "price_per_unit": 2250.00, "fees": 8.50, "currency": "USD", "transacted_at": "2024-02-20T12:00:00Z"},
        {"account_id": crypto_id, "asset_symbol": "SOL", "transaction_type": "BUY", "quantity": 50, "price_per_unit": 105.00, "fees": 5.00, "currency": "USD", "transacted_at": "2024-03-10T10:00:00Z"},
        {"account_id": crypto_id, "asset_symbol": "BTC", "transaction_type": "BUY", "quantity": 0.05, "price_per_unit": 65000.00, "fees": 9.75, "currency": "USD", "transacted_at": "2024-06-15T14:00:00Z"},
        {"account_id": crypto_id, "asset_symbol": "ETH", "transaction_type": "SELL", "quantity": 1.0, "price_per_unit": 3500.00, "fees": 7.00, "currency": "USD", "transacted_at": "2024-07-01T09:00:00Z"},
        {"account_id": crypto_id, "asset_symbol": "SOL", "transaction_type": "STAKE_REWARD", "quantity": 2.5, "price_per_unit": 0, "fees": 0, "currency": "USD", "transacted_at": "2024-09-01T00:00:00Z", "notes": "Staking reward Q3"},
        {"account_id": crypto_id, "asset_symbol": "LINK", "transaction_type": "BUY", "quantity": 100, "price_per_unit": 14.50, "fees": 4.50, "currency": "USD", "transacted_at": "2024-10-15T11:30:00Z"},
        {"account_id": crypto_id, "asset_symbol": "BTC", "transaction_type": "SELL", "quantity": 0.05, "price_per_unit": 95000.00, "fees": 14.25, "currency": "USD", "transacted_at": "2025-01-05T16:00:00Z", "notes": "Profit take at ATH"},
    ]

    created = 0
    errors = 0
    for txn in sample_transactions:
        r = api("POST", "/transactions/", txn, token)
        if r and "id" in r:
            created += 1
        else:
            errors += 1

    print(f"   Created {created} transactions ({errors} errors/duplicates)")

    # 4) Summary
    print("\n" + "=" * 50)
    print(f"  User:     {EMAIL} / {PASSWORD}")
    print(f"  Accounts: {len(accounts)}")
    print(f"  Transactions: {created}")
    print("=" * 50)
    print("\n  Open http://localhost:3000 and sign in with:")
    print(f"    Email:    {EMAIL}")
    print(f"    Password: {PASSWORD}")
    print()


if __name__ == "__main__":
    main()
