"""Tests for services.user_store — PostgreSQL user persistence via asyncpg."""
import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio

from services.match_finder import MSK_TZ

pytestmark = pytest.mark.asyncio


def _fake_user(uid=1):
    return SimpleNamespace(id=uid, username="testuser", first_name="Test", last_name="User")


@pytest_asyncio.fixture()
async def mod(pg_pool):
    """Provide a fresh user_store module backed by a real PG pool."""
    import services.user_store as _mod
    importlib.reload(_mod)
    _mod._pg_pool = pg_pool
    await _mod.init_user_store()
    return _mod


# ── helpers ──────────────────────────────────────────────────────────

async def _insert_promo(mod, code="TESTCODE", active=True, max_uses=10,
                        uses=0, days=30, requests=5):
    await mod._execute(
        "INSERT INTO promo_codes (code, active, max_uses, uses_count, "
        "days_granted, requests_granted) VALUES (?, ?, ?, ?, ?, ?)",
        (code, 1 if active else 0, max_uses, uses, days, requests),
    )


# ── schema / init ───────────────────────────────────────────────────

async def test_init_creates_tables(mod):
    rows = await mod._fetchall(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )
    tables = {r["table_name"] for r in rows}
    assert "users" in tables
    assert "user_events" in tables
    assert "promo_codes" in tables
    assert "schema_version" in tables


async def test_schema_version_table_created(mod):
    row = await mod._fetchone("SELECT MAX(version) AS v FROM schema_version")
    assert row is not None
    assert row["v"] >= 1


async def test_schema_version_idempotent(mod):
    v1 = await mod._fetchone("SELECT MAX(version) AS v FROM schema_version")
    await mod.init_user_store()
    v2 = await mod._fetchone("SELECT MAX(version) AS v FROM schema_version")
    assert v1["v"] == v2["v"]


# ── close_pool ───────────────────────────────────────────────────────

async def test_close_pool_resets_pool(mod):
    assert mod._pg_pool is not None
    await mod.close_pool()
    assert mod._pg_pool is None


# ── touch_user ───────────────────────────────────────────────────────

async def test_touch_user_creates_record(mod):
    await mod.touch_user(_fake_user(), increment_requests=True)
    details = await mod.get_user_details(1)
    assert details is not None
    assert details["requests_count"] == 1


async def test_touch_user_increments_requests(mod):
    user = _fake_user()
    await mod.touch_user(user, increment_requests=True)
    await mod.touch_user(user, increment_requests=True)
    details = await mod.get_user_details(1)
    assert details["requests_count"] == 2


async def test_touch_user_with_discipline(mod):
    await mod.touch_user(_fake_user(), discipline="\u0445\u043e\u043a\u043a\u0435\u0439", match_text="A vs B")
    details = await mod.get_user_details(1)
    assert details["last_discipline"] == "\u0445\u043e\u043a\u043a\u0435\u0439"
    assert details["last_match"] == "A vs B"


async def test_touch_user_default_platform_tg(mod):
    await mod.touch_user(_fake_user())
    details = await mod.get_user_details(1)
    assert details["platform"] == "tg"


async def test_touch_user_custom_platform(mod):
    await mod.touch_user(_fake_user(), platform="vk")
    details = await mod.get_user_details(1)
    assert details["platform"] == "vk"


# ── events / analysis ───────────────────────────────────────────────

async def test_log_user_event(mod):
    await mod.touch_user(_fake_user())
    await mod.log_user_event(1, "test_event", {"key": "value"})
    details = await mod.get_user_details(1)
    assert len(details["recent_events"]) == 1
    assert details["recent_events"][0]["event_type"] == "test_event"


async def test_record_analysis_result_success(mod):
    await mod.touch_user(_fake_user())
    await mod.record_analysis_result(1, discipline="\u0444\u0443\u0442\u0431\u043e\u043b", match_text="A vs B", success=True)
    details = await mod.get_user_details(1)
    assert details["analyses_count"] == 1
    assert details["successful_analyses"] == 1


async def test_record_analysis_result_failure(mod):
    await mod.touch_user(_fake_user())
    await mod.record_analysis_result(1, discipline="\u0444\u0443\u0442\u0431\u043e\u043b", match_text="A vs B", success=False)
    details = await mod.get_user_details(1)
    assert details["analyses_count"] == 1
    assert details["successful_analyses"] == 0


# ── stats / listing ─────────────────────────────────────────────────

async def test_get_stats_summary(mod):
    await mod.touch_user(_fake_user(), increment_requests=True)
    stats = await mod.get_stats_summary()
    assert stats["total_users"] == 1
    assert stats["total_requests"] >= 1


async def test_list_recent_users(mod):
    await mod.touch_user(_fake_user(1))
    await mod.touch_user(_fake_user(2))
    users = await mod.list_recent_users(limit=10)
    assert len(users) == 2


async def test_get_user_details_not_found(mod):
    result = await mod.get_user_details(9999)
    assert result is None


# ── daily limit ──────────────────────────────────────────────────────

@patch("services.user_store.get_msk_now")
async def test_daily_limit_fresh_user(mock_now, mod):
    mock_now.return_value = datetime(2026, 4, 9, 10, 0, 0, tzinfo=MSK_TZ)
    assert await mod.check_daily_limit(999, max_free=3) is True


@patch("services.user_store.get_msk_now")
async def test_daily_limit_increment_and_reset(mock_now, mod):
    mock_now.return_value = datetime(2026, 4, 9, 10, 0, 0, tzinfo=MSK_TZ)
    await mod.touch_user(_fake_user(1))

    await mod.increment_daily_request(1)
    await mod.increment_daily_request(1)
    await mod.increment_daily_request(1)
    assert await mod.check_daily_limit(1, max_free=3) is False

    mock_now.return_value = datetime(2026, 4, 10, 10, 0, 0, tzinfo=MSK_TZ)
    assert await mod.check_daily_limit(1, max_free=3) is True
    await mod.increment_daily_request(1)
    assert await mod.check_daily_limit(1, max_free=3) is True


# ── promo ────────────────────────────────────────────────────────────

async def test_activate_promo_valid_code(mod):
    await mod.touch_user(_fake_user())
    await _insert_promo(mod, "FREE30", active=True, max_uses=10, uses=0, days=30, requests=5)
    result = await mod.activate_promo(1, "FREE30")
    assert result["ok"] is True
    assert "\u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d" in result["message"]


async def test_activate_promo_invalid_code(mod):
    result = await mod.activate_promo(1, "NONEXISTENT")
    assert result["ok"] is False
    assert "\u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d" in result["message"]


async def test_activate_promo_inactive_code(mod):
    await mod.touch_user(_fake_user())
    await _insert_promo(mod, "DEAD", active=False)
    result = await mod.activate_promo(1, "DEAD")
    assert result["ok"] is False
    assert "\u043d\u0435\u0430\u043a\u0442\u0438\u0432\u0435\u043d" in result["message"]


async def test_activate_promo_exhausted_code(mod):
    await mod.touch_user(_fake_user())
    await _insert_promo(mod, "USED", active=True, max_uses=1, uses=1)
    result = await mod.activate_promo(1, "USED")
    assert result["ok"] is False
    assert "\u0438\u0441\u0447\u0435\u0440\u043f\u0430\u043d" in result["message"]


# ── access ───────────────────────────────────────────────────────────

async def test_check_user_access_free_user_within_limit(mod):
    await mod.touch_user(_fake_user())
    result = await mod.check_user_access(1, max_free=3)
    assert result["allowed"] is True


async def test_check_user_access_premium_user(mod):
    await mod.touch_user(_fake_user())
    await mod.activate_subscription(1, days=30)
    result = await mod.check_user_access(1, max_free=3)
    assert result["allowed"] is True


# ── subscription ─────────────────────────────────────────────────────

async def test_activate_subscription(mod):
    await mod.touch_user(_fake_user())
    await mod.activate_subscription(1, days=30)
    details = await mod.get_user_details(1)
    assert details["subscription_status"] == "active"
    assert details.get("subscription_until") is not None


async def test_deactivate_expired_subscriptions(mod):
    await mod.touch_user(_fake_user())
    await mod.activate_subscription(1, days=30)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await mod._execute(
        "UPDATE users SET subscription_until = ? WHERE telegram_user_id = ?",
        (past, 1),
    )
    count = await mod.deactivate_expired_subscriptions()
    assert count == 1
    details = await mod.get_user_details(1)
    assert details["subscription_status"] == "inactive"


# ── _q() placeholder conversion (no DB needed) ──────────────────────

@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_q_converts_placeholders():
    from services.user_store import _q
    assert _q("SELECT * FROM t WHERE a = ? AND b = ?") == "SELECT * FROM t WHERE a = $1 AND b = $2"


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_q_skips_question_mark_inside_string_literal():
    from services.user_store import _q
    result = _q("SELECT * FROM t WHERE name = 'what?' AND id = ?")
    assert "'what?'" in result
    assert "$1" in result
    assert "$2" not in result
"""Tests for services.user_store вЂ” PostgreSQL user persistence via asyncpg."""
import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio

from services.match_finder import MSK_TZ

pytestmark = pytest.mark.asyncio


def _fake_user(uid=1):
    return SimpleNamespace(id=uid, username="testuser", first_name="Test", last_name="User")


@pytest_asyncio.fixture()
async def mod(pg_pool):
    """Provide a fresh user_store module backed by a real PG pool."""
    import services.user_store as _mod
    importlib.reload(_mod)
    _mod._pg_pool = pg_pool
    await _mod.init_user_store()
    return _mod


# в”Ђв”Ђ helpers в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def _insert_promo(mod, code="TESTCODE", active=True, max_uses=10,
                        uses=0, days=30, requests=5):
    await mod._execute(
        "INSERT INTO promo_codes (code, active, max_uses, uses_count, "
        "days_granted, requests_granted) VALUES (?, ?, ?, ?, ?, ?)",
        (code, 1 if active else 0, max_uses, uses, days, requests),
    )


# в”Ђв”Ђ schema / init в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_init_creates_tables(mod):
    rows = await mod._fetchall(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )
    tables = {r["table_name"] for r in rows}
    assert "users" in tables
    assert "user_events" in tables
    assert "promo_codes" in tables
    assert "schema_version" in tables


async def test_schema_version_table_created(mod):
    row = await mod._fetchone("SELECT MAX(version) AS v FROM schema_version")
    assert row is not None
    assert row["v"] >= 1


async def test_schema_version_idempotent(mod):
    v1 = await mod._fetchone("SELECT MAX(version) AS v FROM schema_version")
    await mod.init_user_store()
    v2 = await mod._fetchone("SELECT MAX(version) AS v FROM schema_version")
    assert v1["v"] == v2["v"]


# в”Ђв”Ђ close_pool в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_close_pool_resets_pool(mod):
    assert mod._pg_pool is not None
    await mod.close_pool()
    assert mod._pg_pool is None


# в”Ђв”Ђ touch_user в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_touch_user_creates_record(mod):
    await mod.touch_user(_fake_user(), increment_requests=True)
    details = await mod.get_user_details(1)
    assert details is not None
    assert details["requests_count"] == 1


async def test_touch_user_increments_requests(mod):
    user = _fake_user()
    await mod.touch_user(user, increment_requests=True)
    await mod.touch_user(user, increment_requests=True)
    details = await mod.get_user_details(1)
    assert details["requests_count"] == 2


async def test_touch_user_with_discipline(mod):
    await mod.touch_user(_fake_user(), discipline="хоккей", match_text="A vs B")
    details = await mod.get_user_details(1)
    assert details["last_discipline"] == "хоккей"
    assert details["last_match"] == "A vs B"


async def test_touch_user_default_platform_tg(mod):
    await mod.touch_user(_fake_user())
    details = await mod.get_user_details(1)
    assert details["platform"] == "tg"


async def test_touch_user_custom_platform(mod):
    await mod.touch_user(_fake_user(), platform="vk")
    details = await mod.get_user_details(1)
    assert details["platform"] == "vk"


# в”Ђв”Ђ events / analysis в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_log_user_event(mod):
    await mod.touch_user(_fake_user())
    await mod.log_user_event(1, "test_event", {"key": "value"})
    details = await mod.get_user_details(1)
    assert len(details["recent_events"]) == 1
    assert details["recent_events"][0]["event_type"] == "test_event"


async def test_record_analysis_result_success(mod):
    await mod.touch_user(_fake_user())
    await mod.record_analysis_result(1, discipline="футбол", match_text="A vs B", success=True)
    details = await mod.get_user_details(1)
    assert details["analyses_count"] == 1
    assert details["successful_analyses"] == 1


async def test_record_analysis_result_failure(mod):
    await mod.touch_user(_fake_user())
    await mod.record_analysis_result(1, discipline="футбол", match_text="A vs B", success=False)
    details = await mod.get_user_details(1)
    assert details["analyses_count"] == 1
    assert details["successful_analyses"] == 0


# в”Ђв”Ђ stats / listing в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_get_stats_summary(mod):
    await mod.touch_user(_fake_user(), increment_requests=True)
    stats = await mod.get_stats_summary()
    assert stats["total_users"] == 1
    assert stats["total_requests"] >= 1


async def test_list_recent_users(mod):
    await mod.touch_user(_fake_user(1))
    await mod.touch_user(_fake_user(2))
    users = await mod.list_recent_users(limit=10)
    assert len(users) == 2


async def test_get_user_details_not_found(mod):
    result = await mod.get_user_details(9999)
    assert result is None


# в”Ђв”Ђ daily limit в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@patch("services.user_store.get_msk_now")
async def test_daily_limit_fresh_user(mock_now, mod):
    mock_now.return_value = datetime(2026, 4, 9, 10, 0, 0, tzinfo=MSK_TZ)
    assert await mod.check_daily_limit(999, max_free=3) is True


@patch("services.user_store.get_msk_now")
async def test_daily_limit_increment_and_reset(mock_now, mod):
    mock_now.return_value = datetime(2026, 4, 9, 10, 0, 0, tzinfo=MSK_TZ)
    await mod.touch_user(_fake_user(1))

    await mod.increment_daily_request(1)
    await mod.increment_daily_request(1)
    await mod.increment_daily_request(1)
    assert await mod.check_daily_limit(1, max_free=3) is False

    mock_now.return_value = datetime(2026, 4, 10, 10, 0, 0, tzinfo=MSK_TZ)
    assert await mod.check_daily_limit(1, max_free=3) is True
    await mod.increment_daily_request(1)
    assert await mod.check_daily_limit(1, max_free=3) is True


# в”Ђв”Ђ promo в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_activate_promo_valid_code(mod):
    await mod.touch_user(_fake_user())
    await _insert_promo(mod, "FREE30", active=True, max_uses=10, uses=0, days=30, requests=5)
    result = await mod.activate_promo(1, "FREE30")
    assert result["ok"] is True
    assert "активирован" in result["message"]


async def test_activate_promo_invalid_code(mod):
    result = await mod.activate_promo(1, "NONEXISTENT")
    assert result["ok"] is False
    assert "не найден" in result["message"]


async def test_activate_promo_inactive_code(mod):
    await mod.touch_user(_fake_user())
    await _insert_promo(mod, "DEAD", active=False)
    result = await mod.activate_promo(1, "DEAD")
    assert result["ok"] is False
    assert "неактивен" in result["message"]


async def test_activate_promo_exhausted_code(mod):
    await mod.touch_user(_fake_user())
    await _insert_promo(mod, "USED", active=True, max_uses=1, uses=1)
    result = await mod.activate_promo(1, "USED")
    assert result["ok"] is False
    assert "исчерпан" in result["message"]


# в”Ђв”Ђ access в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_check_user_access_free_user_within_limit(mod):
    await mod.touch_user(_fake_user())
    result = await mod.check_user_access(1, max_free=3)
    assert result["allowed"] is True


async def test_check_user_access_premium_user(mod):
    await mod.touch_user(_fake_user())
    await mod.activate_subscription(1, days=30)
    result = await mod.check_user_access(1, max_free=3)
    assert result["allowed"] is True


# в”Ђв”Ђ subscription в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

async def test_activate_subscription(mod):
    await mod.touch_user(_fake_user())
    await mod.activate_subscription(1, days=30)
    details = await mod.get_user_details(1)
    assert details["subscription_status"] == "active"
    assert details.get("subscription_until") is not None


async def test_deactivate_expired_subscriptions(mod):
    await mod.touch_user(_fake_user())
    await mod.activate_subscription(1, days=30)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await mod._execute(
        "UPDATE users SET subscription_until = ? WHERE telegram_user_id = ?",
        (past, 1),
    )
    count = await mod.deactivate_expired_subscriptions()
    assert count == 1
    details = await mod.get_user_details(1)
    assert details["subscription_status"] == "inactive"


# в”Ђв”Ђ _q() placeholder conversion (no DB needed) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_q_converts_placeholders():
    from services.user_store import _q
    assert _q("SELECT * FROM t WHERE a = ? AND b = ?") == "SELECT * FROM t WHERE a = $1 AND b = $2"


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_q_skips_question_mark_inside_string_literal():
    from services.user_store import _q
    result = _q("SELECT * FROM t WHERE name = 'what?' AND id = ?")
    assert "'what?'" in result
    assert "$1" in result
    assert "$2" not in result
