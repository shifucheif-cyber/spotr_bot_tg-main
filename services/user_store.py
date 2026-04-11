import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- asyncpg connection pool (lazy) ---
_pg_pool = None


async def _get_pool():
    global _pg_pool
    if _pg_pool is None:
        import asyncpg
        _pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=20)
    return _pg_pool


async def close_pool():
    """Close PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None


def _q(sql: str) -> str:
    """Convert '?' placeholders to '$1, $2, ...' for asyncpg.

    Skips '?' inside SQL string literals (single quotes).
    """
    out, n = [], 0
    in_string = False
    for ch in sql:
        if ch == "'":
            in_string = not in_string
        if ch == '?' and not in_string:
            n += 1
            out.append(f'${n}')
        else:
            out.append(ch)
    return ''.join(out)


# --- Async DB helpers ---

async def _fetchone(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    pool = await _get_pool()
    row = await pool.fetchrow(_q(sql), *params)
    return dict(row) if row else None


async def _fetchall(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    pool = await _get_pool()
    rows = await pool.fetch(_q(sql), *params)
    return [dict(r) for r in rows]


async def _fetchval(sql: str, params: tuple = ()):
    """Execute and return the first column of the first row."""
    pool = await _get_pool()
    return await pool.fetchval(_q(sql), *params)


async def _execute(sql: str, params: tuple = ()) -> None:
    pool = await _get_pool()
    await pool.execute(_q(sql), *params)


async def _execute_count(sql: str, params: tuple = ()) -> int:
    """Execute and return number of affected rows."""
    pool = await _get_pool()
    status = await pool.execute(_q(sql), *params)
    return int(status.split()[-1])


# --- Utilities ---

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


from services.match_finder import get_msk_now


# --- Public API (all async) ---

async def init_user_store() -> None:
    users_ddl = """
        CREATE TABLE IF NOT EXISTS users (
            telegram_user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            requests_count INTEGER NOT NULL DEFAULT 0,
            analyses_count INTEGER NOT NULL DEFAULT 0,
            successful_analyses INTEGER NOT NULL DEFAULT 0,
            subscription_status TEXT NOT NULL DEFAULT 'inactive',
            subscription_until TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            last_discipline TEXT,
            last_match TEXT,
            daily_requests INTEGER NOT NULL DEFAULT 0,
            last_request_date TEXT
        )
    """
    events_ddl = """
        CREATE TABLE IF NOT EXISTS user_events (
            id SERIAL PRIMARY KEY,
            telegram_user_id BIGINT NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT NOT NULL,
            details_json TEXT,
            FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
        )
    """
    promo_ddl = """
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            max_uses INTEGER NOT NULL DEFAULT 1,
            uses_count INTEGER NOT NULL DEFAULT 0,
            days_granted INTEGER NOT NULL DEFAULT 0,
            requests_granted INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """

    columns = [
        ("daily_requests", "INTEGER NOT NULL DEFAULT 0"),
        ("last_request_date", "TEXT"),
        ("promo_code", "TEXT"),
        ("promo_until", "TEXT"),
        ("promo_requests_left", "INTEGER"),
    ]

    schema_version_ddl = """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
    """

    MIGRATIONS = [
        [f"ALTER TABLE users ADD COLUMN {col} {defn}" for col, defn in columns],
        ["ALTER TABLE users ADD COLUMN platform TEXT NOT NULL DEFAULT 'tg'"],
    ]

    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(users_ddl)
        await conn.execute(events_ddl)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_events_user_time ON user_events(telegram_user_id, event_time)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_events_type_time ON user_events(event_type, event_time)"
        )
        await conn.execute(promo_ddl)
        await conn.execute(schema_version_ddl)
        row = await conn.fetchrow("SELECT MAX(version) AS v FROM schema_version")
        current_version = (row["v"] or 0) if row else 0
        for idx, stmts in enumerate(MIGRATIONS, start=1):
            if idx <= current_version:
                continue
            for stmt in stmts:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    logger.debug("Migration stmt skipped (likely duplicate): %s", e)
            await conn.execute("INSERT INTO schema_version (version) VALUES ($1)", idx)
        logger.info("DB schema at version %d", max(current_version, len(MIGRATIONS)))


async def check_daily_limit(telegram_user_id: int, max_free: int = 3) -> bool:
    """
    Проверяет, исчерпал ли пользователь суточный лимит по МСК.
    Возвращает True, если можно делать запрос, False — если лимит исчерпан.
    """
    today_date = get_msk_now().strftime('%Y-%m-%d')
    row = await _fetchone(
        "SELECT subscription_status, daily_requests, last_request_date FROM users WHERE telegram_user_id = ?",
        (telegram_user_id,)
    )
    if not row:
        return True
    if row.get("subscription_status") == "active":
        return True
    if row.get("last_request_date") != today_date:
        return True
    return (row.get("daily_requests") or 0) < max_free


async def increment_daily_request(telegram_user_id: int) -> None:
    """
    Увеличивает счетчик суточных запросов пользователя.
    Сбрасывает его, если наступил новый день по МСК.
    """
    today_date = get_msk_now().strftime('%Y-%m-%d')
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                _q("SELECT daily_requests, last_request_date FROM users WHERE telegram_user_id = ?"),
                telegram_user_id
            )
            if not row:
                return
            row = dict(row)
            new_requests = 1 if row.get("last_request_date") != today_date else (row.get("daily_requests") or 0) + 1
            await conn.execute(
                _q("UPDATE users SET daily_requests = ?, last_request_date = ? WHERE telegram_user_id = ?"),
                new_requests, today_date, telegram_user_id
            )


async def upsert_user(user: Any, admin_telegram_id: Optional[int] = None, platform: str = "tg") -> None:
    timestamp = utc_now()
    is_admin = int(bool(admin_telegram_id and user.id == admin_telegram_id))
    await _execute(
        """
        INSERT INTO users (
            telegram_user_id, username, first_name, last_name, first_seen, last_seen, is_admin, platform
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            last_seen=excluded.last_seen,
            is_admin=excluded.is_admin,
            platform=excluded.platform
        """,
        (
            user.id,
            getattr(user, "username", None),
            getattr(user, "first_name", None),
            getattr(user, "last_name", None),
            timestamp,
            timestamp,
            is_admin,
            platform,
        ),
    )


async def touch_user(
    user: Any,
    *,
    admin_telegram_id: Optional[int] = None,
    increment_requests: bool = False,
    discipline: Optional[str] = None,
    match_text: Optional[str] = None,
    platform: str = "tg",
) -> None:
    await upsert_user(user, admin_telegram_id=admin_telegram_id, platform=platform)
    parts = ["last_seen = ?"]
    values: List[Any] = [utc_now()]
    if increment_requests:
        parts.append("requests_count = requests_count + 1")
    if discipline is not None:
        parts.append("last_discipline = ?")
        values.append(discipline)
    if match_text is not None:
        parts.append("last_match = ?")
        values.append(match_text)
    values.append(user.id)
    await _execute(
        f"UPDATE users SET {', '.join(parts)} WHERE telegram_user_id = ?",
        tuple(values),
    )


async def log_user_event(user_id: int, event_type: str, details: Optional[Dict[str, Any]] = None) -> None:
    await _execute(
        "INSERT INTO user_events (telegram_user_id, event_type, event_time, details_json) VALUES (?, ?, ?, ?)",
        (user_id, event_type, utc_now(), json.dumps(details or {}, ensure_ascii=False)),
    )


async def record_analysis_result(
    user_id: int,
    *,
    discipline: Optional[str],
    match_text: Optional[str],
    success: bool,
) -> None:
    await _execute(
        """
        UPDATE users
        SET analyses_count = analyses_count + 1,
            successful_analyses = successful_analyses + ?,
            last_seen = ?,
            last_discipline = COALESCE(?, last_discipline),
            last_match = COALESCE(?, last_match)
        WHERE telegram_user_id = ?
        """,
        (1 if success else 0, utc_now(), discipline, match_text, user_id),
    )
    await log_user_event(
        user_id,
        "analysis_success" if success else "analysis_error",
        {"discipline": discipline, "match": match_text},
    )


async def get_stats_summary() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    total_users = await _fetchval("SELECT COUNT(*) FROM users")
    active_day = await _fetchval("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (day_ago,))
    active_week = await _fetchval("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (week_ago,))
    active_month = await _fetchval("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (month_ago,))
    total_requests = await _fetchval("SELECT COALESCE(SUM(requests_count), 0) FROM users")
    total_analyses = await _fetchval("SELECT COALESCE(SUM(analyses_count), 0) FROM users")
    successful_analyses = await _fetchval("SELECT COALESCE(SUM(successful_analyses), 0) FROM users")
    active_subscriptions = await _fetchval(
        "SELECT COUNT(*) FROM users WHERE subscription_status = 'active' AND (subscription_until IS NULL OR subscription_until >= ?)",
        (utc_now(),),
    )
    top_disciplines = await _fetchall(
        """
        SELECT last_discipline, COUNT(*) AS cnt
        FROM users
        WHERE last_discipline IS NOT NULL AND last_discipline != ''
        GROUP BY last_discipline
        ORDER BY cnt DESC
        LIMIT 5
        """
    )

    return {
        "total_users": total_users,
        "active_day": active_day,
        "active_week": active_week,
        "active_month": active_month,
        "total_requests": total_requests,
        "total_analyses": total_analyses,
        "successful_analyses": successful_analyses,
        "active_subscriptions": active_subscriptions,
        "top_disciplines": [(r["last_discipline"], r["cnt"]) for r in top_disciplines],
    }


async def list_recent_users(limit: int = 20) -> List[Dict[str, Any]]:
    return await _fetchall(
        """
        SELECT telegram_user_id, username, first_name, last_name, last_seen,
               requests_count, analyses_count, subscription_status, is_admin
        FROM users
        ORDER BY last_seen DESC
        LIMIT ?
        """,
        (limit,),
    )


async def get_user_details(telegram_user_id: int) -> Optional[Dict[str, Any]]:
    details = await _fetchone(
        "SELECT * FROM users WHERE telegram_user_id = ?",
        (telegram_user_id,),
    )
    if not details:
        return None
    events = await _fetchall(
        """
        SELECT event_type, event_time, details_json
        FROM user_events
        WHERE telegram_user_id = ?
        ORDER BY event_time DESC
        LIMIT 10
        """,
        (telegram_user_id,),
    )
    details["recent_events"] = events
    return details


async def check_user_access(telegram_user_id: int, max_free: int = 3) -> Dict[str, Any]:
    """Проверяет доступ пользователя: подписка → промо → лимит бесплатных."""
    today_date = get_msk_now().strftime("%Y-%m-%d")
    now_iso = utc_now()

    row = await _fetchone(
        "SELECT subscription_status, subscription_until, daily_requests, "
        "last_request_date, promo_until, promo_requests_left FROM users WHERE telegram_user_id = ?",
        (telegram_user_id,),
    )

    if not row:
        return {"allowed": True, "reason": "new_user", "requests_left": max_free}

    # 1) Active subscription
    sub_status = row.get("subscription_status", "inactive")
    sub_until = row.get("subscription_until")
    if sub_status == "active" and (not sub_until or sub_until >= now_iso):
        return {"allowed": True, "reason": "subscription", "requests_left": -1}

    # 2) Active promo
    promo_until = row.get("promo_until")
    promo_left = row.get("promo_requests_left")
    if promo_until and promo_until >= now_iso and promo_left and promo_left > 0:
        return {"allowed": True, "reason": "promo", "requests_left": promo_left}

    # 3) Free daily limit
    last_date = row.get("last_request_date")
    daily = row.get("daily_requests") or 0
    if last_date != today_date:
        return {"allowed": True, "reason": "free", "requests_left": max_free}
    remaining = max_free - daily
    if remaining > 0:
        return {"allowed": True, "reason": "free", "requests_left": remaining}

    return {"allowed": False, "reason": "limit_reached", "requests_left": 0}


async def activate_promo(telegram_user_id: int, promo_code: str) -> Dict[str, Any]:
    """Активирует промокод для пользователя. Возвращает {ok: bool, message: str}."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            promo_row = await conn.fetchrow(
                _q("SELECT * FROM promo_codes WHERE code = ?"), promo_code
            )
            if not promo_row:
                return {"ok": False, "message": "Промокод не найден."}
            promo = dict(promo_row)
            if not promo.get("active"):
                return {"ok": False, "message": "Промокод неактивен."}
            if promo.get("uses_count", 0) >= promo.get("max_uses", 1):
                return {"ok": False, "message": "Промокод исчерпан."}

            days = promo.get("days_granted", 0)
            requests = promo.get("requests_granted", 0)
            promo_until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days > 0 else None

            await conn.execute(
                _q("UPDATE users SET promo_code = ?, promo_until = ?, promo_requests_left = ? WHERE telegram_user_id = ?"),
                promo_code, promo_until, requests if requests > 0 else None, telegram_user_id
            )
            await conn.execute(
                _q("UPDATE promo_codes SET uses_count = uses_count + 1 WHERE code = ?"),
                promo_code
            )
    return {"ok": True, "message": f"Промокод активирован! Дней: {days}, запросов: {requests}."}


async def activate_subscription(telegram_user_id: int, days: int) -> None:
    """Активирует подписку на указанное количество дней."""
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    await _execute(
        "UPDATE users SET subscription_status = 'active', subscription_until = ? WHERE telegram_user_id = ?",
        (until, telegram_user_id),
    )


async def deactivate_expired_subscriptions() -> int:
    """Деактивирует истёкшие подписки. Возвращает количество деактивированных."""
    now_iso = utc_now()
    return await _execute_count(
        "UPDATE users SET subscription_status = 'inactive' "
        "WHERE subscription_status = 'active' AND subscription_until IS NOT NULL AND subscription_until < ?",
        (now_iso,),
    )
