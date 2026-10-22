"""
Repair ASX securities that were stored as USD assets.

Older imports reused an existing asset row by symbol alone, so an ASX holding
(e.g. CBA from a CommSec CSV) could end up attached to a USD asset. It was then
priced from the US ticker (or the .AX price was FX-converted a second time), and
the US dividend sync attached US dividends to it.

A USD equity/ETF is treated as mis-tagged when every account holding it is an
AUD account and at least one of its trades is in AUD. For each one this script:
  - retags it as AUD, or merges it into an existing AUD asset with the same symbol
  - deletes POLYGON_DIVIDEND rows on it (those are US-listing dividends)

Dry run by default; review the list before applying.
Run: docker compose exec backend python scripts/repair_asx_assets.py [--apply] [--symbols CBA,BHP]
"""
import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import delete, func, select, update

from database import AsyncSessionLocal
from shared.models import Account, Asset, Holding, Price, TaxLot, Transaction


async def find_candidates(db, symbols: set[str] | None) -> list[Asset]:
    query = select(Asset).where(Asset.currency == "USD", Asset.asset_class != "CRYPTO")
    if symbols:
        query = query.where(Asset.symbol.in_(symbols))
    candidates = []
    for asset in (await db.execute(query.order_by(Asset.symbol))).scalars():
        account_ccys, aud_trades = (await db.execute(
            select(
                func.array_agg(func.distinct(Account.currency)),
                func.count().filter(Transaction.currency == "AUD"),
            )
            .join(Account, Account.id == Transaction.account_id)
            .where(Transaction.asset_id == asset.id, Transaction.source != "POLYGON_DIVIDEND")
        )).one()
        if account_ccys and set(account_ccys) == {"AUD"} and aud_trades > 0:
            candidates.append(asset)
    return candidates


async def repair(apply: bool, symbols: set[str] | None) -> None:
    async with AsyncSessionLocal() as db:
        candidates = await find_candidates(db, symbols)
        if not candidates:
            print("No mis-tagged ASX assets found.")
            return

        for asset in candidates:
            twin = (await db.execute(
                select(Asset).where(
                    Asset.symbol == asset.symbol,
                    Asset.currency == "AUD",
                    Asset.asset_class != "CRYPTO",
                ).order_by(Asset.created_at).limit(1)
            )).scalar_one_or_none()

            us_dividends = (await db.execute(
                delete(Transaction).where(
                    Transaction.asset_id == asset.id,
                    Transaction.source == "POLYGON_DIVIDEND",
                )
            )).rowcount

            if twin:
                for model, col in (
                    (Transaction, Transaction.asset_id),
                    (Transaction, Transaction.related_asset_id),
                    (Holding, Holding.asset_id),
                    (Price, Price.asset_id),
                    (TaxLot, TaxLot.asset_id),
                ):
                    await db.execute(update(model).where(col == asset.id).values({col.key: twin.id}))
                await db.delete(asset)
                action = f"merged into existing AUD asset {twin.id}"
            else:
                asset.currency = "AUD"
                action = "retagged USD -> AUD"

            print(f"{asset.symbol:8} {action}; removed {us_dividends} US dividend row(s)")

        if apply:
            await db.commit()
            print(f"\nApplied to {len(candidates)} asset(s). Restart the backend or wait ~5 min for cached summaries to expire.")
        else:
            await db.rollback()
            print(f"\nDry run: {len(candidates)} asset(s) would change. Re-run with --apply to commit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="commit the changes (default: dry run)")
    parser.add_argument("--symbols", help="comma-separated symbols to limit the repair to")
    args = parser.parse_args()
    only = {s.strip().upper() for s in args.symbols.split(",")} if args.symbols else None
    asyncio.run(repair(args.apply, only))
