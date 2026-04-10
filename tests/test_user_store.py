"""Tests for services.user_store — SQLite/PostgreSQL user persistence."""
import os
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace


from datetime import datetime, timedelta, timezone
from services.match_finder import MSK_TZ

class TestUserStore(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Use shared in-memory SQLite via file URI for isolation."""
        self._patcher = patch.dict(os.environ, {"DB_BACKEND": "sqlite"})
        self._patcher.start()
        import importlib
        import services.user_store as mod
        importlib.reload(mod)
        self.mod = mod
        # Use a shared in-memory DB (same connection pool via URI)
        import sqlite3
        self._db_uri = "file:test_user_store?mode=memory&cache=shared"
        self._keepalive = sqlite3.connect(self._db_uri, uri=True)
        self._orig_get_conn = mod.get_connection

        def _test_conn():
            conn = sqlite3.connect(self._db_uri, uri=True)
            conn.row_factory = sqlite3.Row
            return conn

        mod.get_connection = _test_conn
        await mod.init_user_store()

    async def asyncTearDown(self):
        self.mod.get_connection = self._orig_get_conn
        self._keepalive.close()
        self._patcher.stop()

    def _fake_user(self, uid=1):
        return SimpleNamespace(id=uid, username="testuser", first_name="Test", last_name="User")

    async def test_init_creates_tables(self):
        conn = self.mod.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        self.assertIn("users", tables)
        self.assertIn("user_events", tables)

    async def test_touch_user_creates_record(self):
        user = self._fake_user()
        await self.mod.touch_user(user, increment_requests=True)
        details = await self.mod.get_user_details(1)
        self.assertIsNotNone(details)
        self.assertEqual(details["requests_count"], 1)

    async def test_touch_user_increments_requests(self):
        user = self._fake_user()
        await self.mod.touch_user(user, increment_requests=True)
        await self.mod.touch_user(user, increment_requests=True)
        details = await self.mod.get_user_details(1)
        self.assertEqual(details["requests_count"], 2)

    async def test_log_user_event(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self.mod.log_user_event(1, "test_event", {"key": "value"})
        details = await self.mod.get_user_details(1)
        self.assertEqual(len(details["recent_events"]), 1)
        self.assertEqual(details["recent_events"][0]["event_type"], "test_event")

    async def test_record_analysis_result_success(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self.mod.record_analysis_result(1, discipline="футбол", match_text="A vs B", success=True)
        details = await self.mod.get_user_details(1)
        self.assertEqual(details["analyses_count"], 1)
        self.assertEqual(details["successful_analyses"], 1)

    async def test_record_analysis_result_failure(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self.mod.record_analysis_result(1, discipline="футбол", match_text="A vs B", success=False)
        details = await self.mod.get_user_details(1)
        self.assertEqual(details["analyses_count"], 1)
        self.assertEqual(details["successful_analyses"], 0)

    async def test_get_stats_summary(self):
        user = self._fake_user()
        await self.mod.touch_user(user, increment_requests=True)
        stats = await self.mod.get_stats_summary()
        self.assertEqual(stats["total_users"], 1)
        self.assertGreaterEqual(stats["total_requests"], 1)

    async def test_list_recent_users(self):
        await self.mod.touch_user(self._fake_user(1))
        await self.mod.touch_user(self._fake_user(2))
        users = await self.mod.list_recent_users(limit=10)
        self.assertEqual(len(users), 2)

    async def test_get_user_details_not_found(self):
        result = await self.mod.get_user_details(9999)
        self.assertIsNone(result)

    async def test_touch_user_with_discipline(self):
        user = self._fake_user()
        await self.mod.touch_user(user, discipline="хоккей", match_text="A vs B")
        details = await self.mod.get_user_details(1)
        self.assertEqual(details["last_discipline"], "хоккей")
        self.assertEqual(details["last_match"], "A vs B")

    @patch('services.user_store.get_msk_now')
    async def test_daily_limit_fresh_user(self, mock_now):
        mock_now.return_value = datetime(2026, 4, 9, 10, 0, 0, tzinfo=MSK_TZ)
        self.assertTrue(await self.mod.check_daily_limit(999, max_free=3))

    @patch('services.user_store.get_msk_now')
    async def test_daily_limit_increment_and_reset(self, mock_now):
        mock_now.return_value = datetime(2026, 4, 9, 10, 0, 0, tzinfo=MSK_TZ)
        user = self._fake_user(1)
        await self.mod.touch_user(user)

        await self.mod.increment_daily_request(1)
        await self.mod.increment_daily_request(1)
        await self.mod.increment_daily_request(1)
        
        # 3 requests, limit is 3 => False
        self.assertFalse(await self.mod.check_daily_limit(1, max_free=3))

        # Next day
        mock_now.return_value = datetime(2026, 4, 10, 10, 0, 0, tzinfo=MSK_TZ)
        self.assertTrue(await self.mod.check_daily_limit(1, max_free=3))

        await self.mod.increment_daily_request(1)
        self.assertTrue(await self.mod.check_daily_limit(1, max_free=3))

    # --- activate_promo tests ---

    async def _insert_promo(self, code="TESTCODE", active=True, max_uses=10, uses=0, days=30, requests=5):
        conn = self.mod.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            self.mod._q(
                "INSERT INTO promo_codes (code, active, max_uses, uses_count, days_granted, requests_granted) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            ),
            (code, 1 if active else 0, max_uses, uses, days, requests),
        )
        conn.commit()
        conn.close()

    async def test_activate_promo_valid_code(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self._insert_promo("FREE30", active=True, max_uses=10, uses=0, days=30, requests=5)
        result = await self.mod.activate_promo(1, "FREE30")
        self.assertTrue(result["ok"])
        self.assertIn("активирован", result["message"])

    async def test_activate_promo_invalid_code(self):
        result = await self.mod.activate_promo(1, "NONEXISTENT")
        self.assertFalse(result["ok"])
        self.assertIn("не найден", result["message"])

    async def test_activate_promo_inactive_code(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self._insert_promo("DEAD", active=False)
        result = await self.mod.activate_promo(1, "DEAD")
        self.assertFalse(result["ok"])
        self.assertIn("неактивен", result["message"])

    async def test_activate_promo_exhausted_code(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self._insert_promo("USED", active=True, max_uses=1, uses=1)
        result = await self.mod.activate_promo(1, "USED")
        self.assertFalse(result["ok"])
        self.assertIn("исчерпан", result["message"])

    # --- check_user_access tests ---

    async def test_check_user_access_free_user_within_limit(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        result = await self.mod.check_user_access(1, max_free=3)
        self.assertTrue(result["allowed"])

    async def test_check_user_access_premium_user(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self.mod.activate_subscription(1, days=30)
        result = await self.mod.check_user_access(1, max_free=3)
        self.assertTrue(result["allowed"])

    # --- activate_subscription tests ---

    async def test_activate_subscription(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        await self.mod.activate_subscription(1, days=30)
        details = await self.mod.get_user_details(1)
        self.assertEqual(details["subscription_status"], "active")
        self.assertIsNotNone(details.get("subscription_until"))

    # --- deactivate_expired_subscriptions tests ---

    async def test_deactivate_expired_subscriptions(self):
        user = self._fake_user()
        await self.mod.touch_user(user)
        # Activate then manually set subscription_until to past
        await self.mod.activate_subscription(1, days=30)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn = self.mod.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            self.mod._q("UPDATE users SET subscription_until = ? WHERE telegram_user_id = ?"),
            (past, 1),
        )
        conn.commit()
        conn.close()
        count = await self.mod.deactivate_expired_subscriptions()
        self.assertEqual(count, 1)
        details = await self.mod.get_user_details(1)
        self.assertEqual(details["subscription_status"], "inactive")

if __name__ == "__main__":
    unittest.main()
