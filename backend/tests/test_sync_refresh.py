import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers.sync import refresh_all


class SyncRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_all_syncs_ibkr_and_reports_imported_transactions(self):
        credential = SimpleNamespace(account_id="account-1", provider="IBKR")
        scalars = MagicMock()
        scalars.all.return_value = [credential]
        query_result = MagicMock()
        query_result.scalars.return_value = scalars
        db = SimpleNamespace(execute=AsyncMock(return_value=query_result))
        user = SimpleNamespace(id="user-1")

        service = MagicMock()
        service.sync_account = AsyncMock(
            return_value={"provider": "ibkr", "imported": 2}
        )
        service.close = AsyncMock()

        with (
            patch("routers.sync.cache_delete_pattern", AsyncMock(side_effect=[3, 1])),
            patch("routers.sync.cache_invalidate_user", AsyncMock()),
            patch("routers.sync.SyncService", return_value=service),
        ):
            result = await refresh_all(current_user=user, db=db)

        service.sync_account.assert_awaited_once_with(
            "account-1", "user-1", recent_only=True
        )
        service.close.assert_awaited_once()
        self.assertEqual(result["accounts_synced"], 1)
        self.assertEqual(result["total_imported"], 2)
        self.assertEqual(result["errors"], [])

    async def test_refresh_all_surfaces_provider_errors(self):
        credential = SimpleNamespace(account_id="account-1", provider="IBKR")
        scalars = MagicMock()
        scalars.all.return_value = [credential]
        query_result = MagicMock()
        query_result.scalars.return_value = scalars
        db = SimpleNamespace(execute=AsyncMock(return_value=query_result))
        user = SimpleNamespace(id="user-1")

        service = MagicMock()
        service.sync_account = AsyncMock(
            return_value={"provider": "ibkr", "imported": 0, "error": "Flex failed"}
        )
        service.close = AsyncMock()

        with (
            patch("routers.sync.cache_delete_pattern", AsyncMock(side_effect=[0, 0])),
            patch("routers.sync.cache_invalidate_user", AsyncMock()),
            patch("routers.sync.SyncService", return_value=service),
        ):
            result = await refresh_all(current_user=user, db=db)

        self.assertEqual(result["total_imported"], 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["error"], "Flex failed")


if __name__ == "__main__":
    unittest.main()
