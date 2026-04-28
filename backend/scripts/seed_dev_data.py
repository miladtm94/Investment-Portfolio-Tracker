"""
Development data seeder.
Creates demo user, accounts, assets, and transactions.
Run: python scripts/seed_dev_data.py
"""
import asyncio
import sys
import os

sys.path.insert(0, '/app')

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import random

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from shared.models import Base, User, Account, Asset, Transaction
from shared.auth import hash_password
from config import get_settings

settings = get_settings()


async def seed():
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as db:
        # ── User ─────────────────────────────────────────────────────────
        user = User(
            email="demo@investiq.io",
            password_hash=hash_password("demo1234"),
            full_name="Demo User",
            preferred_currency="USD",
            cost_basis_method="FIFO",
        )
        db.add(user)
        await db.flush()

        # ── Accounts ─────────────────────────────────────────────────────
        brokerage = Account(user_id=user.id, name="Fidelity Brokerage", account_type="BROKERAGE", institution_name="Fidelity")
        crypto_acct = Account(user_id=user.id, name="Coinbase Exchange", account_type="CRYPTO_EXCHANGE", institution_name="Coinbase")
        ira = Account(user_id=user.id, name="Roth IRA", account_type="IRA", account_subtype="ROTH", institution_name="Fidelity", is_taxable=False)
        db.add_all([brokerage, crypto_acct, ira])
        await db.flush()

        # ── Assets ───────────────────────────────────────────────────────
        EQUITIES = [
            ("AAPL", "Apple Inc.", "EQUITY", "NASDAQ", "Technology", "US"),
            ("MSFT", "Microsoft Corp.", "EQUITY", "NASDAQ", "Technology", "US"),
            ("GOOGL", "Alphabet Inc.", "EQUITY", "NASDAQ", "Communication Services", "US"),
            ("AMZN", "Amazon.com Inc.", "EQUITY", "NASDAQ", "Consumer Discretionary", "US"),
            ("NVDA", "NVIDIA Corporation", "EQUITY", "NASDAQ", "Technology", "US"),
            ("JPM", "JPMorgan Chase", "EQUITY", "NYSE", "Financials", "US"),
            ("JNJ", "Johnson & Johnson", "EQUITY", "NYSE", "Healthcare", "US"),
            ("SPY", "SPDR S&P 500 ETF", "ETF", "NYSE", "Broad Market", "US"),
            ("QQQ", "Invesco QQQ ETF", "ETF", "NASDAQ", "Technology", "US"),
            ("AGG", "iShares US Agg Bond ETF", "ETF", "NYSE", "Fixed Income", "US"),
        ]
        CRYPTOS = [
            ("BTC", "Bitcoin", "CRYPTO", None, "Cryptocurrency", "Global"),
            ("ETH", "Ethereum", "CRYPTO", None, "Cryptocurrency", "Global"),
            ("SOL", "Solana", "CRYPTO", None, "Cryptocurrency", "Global"),
        ]

        assets_by_symbol: dict[str, Asset] = {}
        for sym, name, cls, exch, sector, country in EQUITIES + CRYPTOS:
            a = Asset(symbol=sym, name=name, asset_class=cls, exchange=exch, sector=sector, country=country)
            db.add(a)
            assets_by_symbol[sym] = a

        await db.flush()

        # ── Transactions ─────────────────────────────────────────────────
        now = datetime.now(timezone.utc)

        def txn(account_id, symbol, typ, qty, price, date_offset_days, fees=0.0):
            a = assets_by_symbol[symbol]
            qty_d = Decimal(str(qty))
            price_d = Decimal(str(price))
            fees_d = Decimal(str(fees))
            dt = now - timedelta(days=date_offset_days)
            net = qty_d * price_d - fees_d if typ == "SELL" else -(qty_d * price_d + fees_d)
            return Transaction(
                account_id=account_id, user_id=user.id,
                asset_id=a.id, transaction_type=typ,
                quantity=qty_d, price_per_unit=price_d, fees=fees_d, net_amount=net,
                currency="USD", transacted_at=dt, source="SEED",
                import_hash=f"seed-{account_id}-{symbol}-{typ}-{date_offset_days}",
            )

        transactions = [
            # Brokerage: long-term equity positions
            txn(brokerage.id, "AAPL", "BUY", 50, 142.50, 500, fees=4.95),
            txn(brokerage.id, "AAPL", "BUY", 25, 168.00, 200, fees=4.95),
            txn(brokerage.id, "MSFT", "BUY", 30, 310.00, 450, fees=4.95),
            txn(brokerage.id, "NVDA", "BUY", 20, 290.00, 600, fees=4.95),
            txn(brokerage.id, "NVDA", "BUY", 15, 450.00, 180, fees=4.95),
            txn(brokerage.id, "GOOGL", "BUY", 10, 105.00, 550, fees=4.95),
            txn(brokerage.id, "JPM", "BUY", 40, 155.00, 400, fees=4.95),
            txn(brokerage.id, "SPY", "BUY", 100, 395.00, 700, fees=0),
            txn(brokerage.id, "QQQ", "BUY", 50, 335.00, 650, fees=0),
            txn(brokerage.id, "AGG", "BUY", 200, 97.50, 300, fees=0),
            # Some realized gain
            txn(brokerage.id, "JPM", "SELL", 10, 200.00, 30, fees=4.95),
            # Dividends
            Transaction(
                account_id=brokerage.id, user_id=user.id,
                asset_id=assets_by_symbol["AAPL"].id, transaction_type="DIVIDEND",
                quantity=None, fees=Decimal("0"),
                net_amount=Decimal("42.50"), net_amount_usd=Decimal("42.50"),
                currency="USD", transacted_at=now - timedelta(days=90), source="SEED",
                import_hash="seed-div-aapl-1",
            ),
            Transaction(
                account_id=brokerage.id, user_id=user.id,
                asset_id=assets_by_symbol["SPY"].id, transaction_type="DIVIDEND",
                quantity=None, fees=Decimal("0"),
                net_amount=Decimal("118.75"), net_amount_usd=Decimal("118.75"),
                currency="USD", transacted_at=now - timedelta(days=45), source="SEED",
                import_hash="seed-div-spy-1",
            ),

            # Crypto: mixed positions
            txn(crypto_acct.id, "BTC", "BUY", 0.5, 28000.00, 800, fees=14.0),
            txn(crypto_acct.id, "BTC", "BUY", 0.25, 42000.00, 400, fees=10.5),
            txn(crypto_acct.id, "ETH", "BUY", 5.0, 1800.00, 700, fees=9.0),
            txn(crypto_acct.id, "ETH", "BUY", 3.0, 2400.00, 300, fees=7.2),
            txn(crypto_acct.id, "SOL", "BUY", 50, 18.00, 600, fees=0.9),
            txn(crypto_acct.id, "SOL", "BUY", 30, 85.00, 100, fees=2.55),
            # Staking rewards
            Transaction(
                account_id=crypto_acct.id, user_id=user.id,
                asset_id=assets_by_symbol["ETH"].id, transaction_type="STAKE_REWARD",
                quantity=Decimal("0.15"), price_per_unit=Decimal("2200.00"),
                fees=Decimal("0"), net_amount=Decimal("330.00"), net_amount_usd=Decimal("330.00"),
                currency="USD", transacted_at=now - timedelta(days=60), source="SEED",
                import_hash="seed-stake-eth-1",
            ),
            Transaction(
                account_id=crypto_acct.id, user_id=user.id,
                asset_id=assets_by_symbol["SOL"].id, transaction_type="STAKE_REWARD",
                quantity=Decimal("2.5"), price_per_unit=Decimal("95.00"),
                fees=Decimal("0"), net_amount=Decimal("237.50"), net_amount_usd=Decimal("237.50"),
                currency="USD", transacted_at=now - timedelta(days=30), source="SEED",
                import_hash="seed-stake-sol-1",
            ),

            # IRA
            txn(ira.id, "SPY", "BUY", 200, 380.00, 900, fees=0),
            txn(ira.id, "QQQ", "BUY", 100, 300.00, 900, fees=0),
            txn(ira.id, "JNJ", "BUY", 60, 165.00, 800, fees=4.95),
            txn(ira.id, "MSFT", "BUY", 20, 280.00, 800, fees=4.95),
        ]

        db.add_all(transactions)
        await db.commit()

        print(f"\n✅ Seeded dev data successfully!")
        print(f"   User: demo@investiq.io / demo1234")
        print(f"   Accounts: {brokerage.name}, {crypto_acct.name}, {ira.name}")
        print(f"   Assets: {len(assets_by_symbol)}")
        print(f"   Transactions: {len(transactions)}")
        print(f"\n   API: http://localhost:8010/docs")
        print(f"   Frontend: http://localhost:3000")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
