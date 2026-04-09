import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").lower()
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_PATH = Path(os.getenv("BOT_DB_PATH", BASE_DIR / "bot_data.sqlite3"))

_PH = "%s" if DB_BACKEND == "postgres" else "?"


def _q(sql: str) -> str:
    """Convert '?' placeholders to '%s' for PostgreSQL."""
    if DB_BACKEND == "postgres":
        return sql.replace("?", "%s")
    return sql


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    """Return a DB connection (sqlite3 or psycopg2) based on DB_BACKEND."""
    if DB_BACKEND == "postgres":
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise RuntimeError("psycopg2 not installed. Run: pip install psycopg2-binary")
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _fetchone_dict(cursor, row) -> Optional[Dict[str, Any]]:
    """Convert a row to dict regardless of backend."""
    if row is None:
        return None
    if DB_BACKEND == "postgres":
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    return dict(row)


def _fetchall_dicts(cursor, rows) -> List[Dict[str, Any]]:
    """Convert rows to list of dicts regardless of backend."""
    if DB_BACKEND == "postgres":
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    return [dict(row) for row in rows]


def init_user_store() -> None:
    if DB_BACKEND == "sqlite":
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

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
    if DB_BACKEND == "postgres":
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
    else:
        events_ddl = """
            CREATE TABLE IF NOT EXISTS user_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL,
                details_json TEXT,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
            )
        """

    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(users_ddl)
        cursor.execute(events_ddl)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_events_user_time ON user_events(telegram_user_id, event_time)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_events_type_time ON user_events(event_type, event_time)"
        )
        
        # Add new columns safely
        columns = [
            ("daily_requests", "INTEGER NOT NULL DEFAULT 0"),
            ("last_request_date", "TEXT"),
            ("promo_code", "TEXT"),
            ("promo_until", "TEXT"),
            ("promo_requests_left", "INTEGER"),
        ]
        for col_name, col_def in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
            except Exception as e:
                pass # Safe to ignore if column already exists

        connection.commit()

    # promo_codes table
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
    with closing(get_connection()) as connection:
        connection.cursor().execute(promo_ddl)
        connection.commit()

from services.match_finder import get_msk_now

def check_daily_limit(telegram_user_id: int, max_free: int = 3) -> bool:
    """
    Проверяет, исчерпал ли пользователь суточный лимит по МСК.
    Возвращает True, если можно делать запрос, False — если лимит исчерпан.
    """
    today_date = get_msk_now().strftime('%Y-%m-%d')
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("SELECT subscription_status, daily_requests, last_request_date FROM users WHERE telegram_user_id = ?"),
            (telegram_user_id,)
        )
        row = _fetchone_dict(cursor, cursor.fetchone())

        if not row:
            return True  # Новый пользователь

        if row.get("subscription_status") == "active":
            return True  # Безлимит для premium

        # Если день сменился, лимит сброшен
        if row.get("last_request_date") != today_date:
            return True
            
        requests_today = row.get("daily_requests") or 0
        return requests_today < max_free


def increment_daily_request(telegram_user_id: int) -> None:
    """
    Увеличивает счетчик суточных запросов пользователя.
    Сбрасывает его, если наступил новый день по МСК.
    """
    today_date = get_msk_now().strftime('%Y-%m-%d')
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("SELECT daily_requests, last_request_date FROM users WHERE telegram_user_id = ?"),
            (telegram_user_id,)
        )
        row = _fetchone_dict(cursor, cursor.fetchone())
        
        if not row:
            return

        last_date = row.get("last_request_date")
        
        if last_date != today_date:
            new_requests = 1
        else:
            new_requests = (row.get("daily_requests") or 0) + 1
            
        cursor.execute(
            _q("UPDATE users SET daily_requests = ?, last_request_date = ? WHERE telegram_user_id = ?"),
            (new_requests, today_date, telegram_user_id)
        )
        connection.commit()


def upsert_user(user: Any, admin_telegram_id: Optional[int] = None) -> None:
    timestamp = utc_now()
    is_admin = int(bool(admin_telegram_id and user.id == admin_telegram_id))
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("""
            INSERT INTO users (
                telegram_user_id, username, first_name, last_name, first_seen, last_seen, is_admin
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen=excluded.last_seen,
                is_admin=excluded.is_admin
            """),
            (
                user.id,
                getattr(user, "username", None),
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
                timestamp,
                timestamp,
                is_admin,
            ),
        )
        connection.commit()


def touch_user(
    user: Any,
    *,
    admin_telegram_id: Optional[int] = None,
    increment_requests: bool = False,
    discipline: Optional[str] = None,
    match_text: Optional[str] = None,
) -> None:
    upsert_user(user, admin_telegram_id=admin_telegram_id)
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
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
        cursor.execute(
            _q(f"UPDATE users SET {', '.join(parts)} WHERE telegram_user_id = ?"),
            values,
        )
        connection.commit()


def log_user_event(user_id: int, event_type: str, details: Optional[Dict[str, Any]] = None) -> None:
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("INSERT INTO user_events (telegram_user_id, event_type, event_time, details_json) VALUES (?, ?, ?, ?)"),
            (user_id, event_type, utc_now(), json.dumps(details or {}, ensure_ascii=False)),
        )
        connection.commit()


def record_analysis_result(
    user_id: int,
    *,
    discipline: Optional[str],
    match_text: Optional[str],
    success: bool,
) -> None:
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("""
            UPDATE users
            SET analyses_count = analyses_count + 1,
                successful_analyses = successful_analyses + ?,
                last_seen = ?,
                last_discipline = COALESCE(?, last_discipline),
                last_match = COALESCE(?, last_match)
            WHERE telegram_user_id = ?
            """),
            (1 if success else 0, utc_now(), discipline, match_text, user_id),
        )
        connection.commit()

    log_user_event(
        user_id,
        "analysis_success" if success else "analysis_error",
        {"discipline": discipline, "match": match_text},
    )


def get_stats_summary() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        total_users = cursor.execute(_q("SELECT COUNT(*) FROM users")).fetchone()[0]
        active_day = cursor.execute(_q("SELECT COUNT(*) FROM users WHERE last_seen >= ?"), (day_ago,)).fetchone()[0]
        active_week = cursor.execute(_q("SELECT COUNT(*) FROM users WHERE last_seen >= ?"), (week_ago,)).fetchone()[0]
        active_month = cursor.execute(_q("SELECT COUNT(*) FROM users WHERE last_seen >= ?"), (month_ago,)).fetchone()[0]
        total_requests = cursor.execute(_q("SELECT COALESCE(SUM(requests_count), 0) FROM users")).fetchone()[0]
        total_analyses = cursor.execute(_q("SELECT COALESCE(SUM(analyses_count), 0) FROM users")).fetchone()[0]
        successful_analyses = cursor.execute(_q("SELECT COALESCE(SUM(successful_analyses), 0) FROM users")).fetchone()[0]
        active_subscriptions = cursor.execute(
            _q("SELECT COUNT(*) FROM users WHERE subscription_status = 'active' AND (subscription_until IS NULL OR subscription_until >= ?)"),
            (utc_now(),),
        ).fetchone()[0]
        top_disciplines = cursor.execute(
            """
            SELECT last_discipline, COUNT(*) AS cnt
            FROM users
            WHERE last_discipline IS NOT NULL AND last_discipline != ''
            GROUP BY last_discipline
            ORDER BY cnt DESC
            LIMIT 5
            """
        ).fetchall()

    return {
        "total_users": total_users,
        "active_day": active_day,
        "active_week": active_week,
        "active_month": active_month,
        "total_requests": total_requests,
        "total_analyses": total_analyses,
        "successful_analyses": successful_analyses,
        "active_subscriptions": active_subscriptions,
        "top_disciplines": [(row[0], row[1]) for row in top_disciplines],
    }


def list_recent_users(limit: int = 20) -> List[Dict[str, Any]]:
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("""
            SELECT telegram_user_id, username, first_name, last_name, last_seen,
                   requests_count, analyses_count, subscription_status, is_admin
            FROM users
            ORDER BY last_seen DESC
            LIMIT ?
            """),
            (limit,),
        )
        rows = cursor.fetchall()
        return _fetchall_dicts(cursor, rows)


def get_user_details(telegram_user_id: int) -> Optional[Dict[str, Any]]:
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("SELECT * FROM users WHERE telegram_user_id = ?"),
            (telegram_user_id,),
        )
        user_row = cursor.fetchone()
        if not user_row:
            return None

        cursor.execute(
            _q("""
            SELECT event_type, event_time, details_json
            FROM user_events
            WHERE telegram_user_id = ?
            ORDER BY event_time DESC
            LIMIT 10
            """),
            (telegram_user_id,),
        )
        event_rows = cursor.fetchall()

        details = _fetchone_dict(cursor, user_row)
        details["recent_events"] = _fetchall_dicts(cursor, event_rows)
        return details


def check_user_access(telegram_user_id: int, max_free: int = 3) -> Dict[str, Any]:
    """Проверяет доступ пользователя: подписка → промо → лимит бесплатных."""
    today_date = get_msk_now().strftime("%Y-%m-%d")
    now_iso = utc_now()

    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("SELECT subscription_status, subscription_until, daily_requests, "
               "last_request_date, promo_until, promo_requests_left FROM users WHERE telegram_user_id = ?"),
            (telegram_user_id,),
        )
        row = _fetchone_dict(cursor, cursor.fetchone())

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


def activate_promo(telegram_user_id: int, promo_code: str) -> Dict[str, Any]:
    """Активирует промокод для пользователя. Возвращает {ok: bool, message: str}."""
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(_q("SELECT * FROM promo_codes WHERE code = ?"), (promo_code,))
        promo = _fetchone_dict(cursor, cursor.fetchone())

        if not promo:
            return {"ok": False, "message": "Промокод не найден."}
        if not promo.get("active"):
            return {"ok": False, "message": "Промокод неактивен."}
        if promo.get("uses_count", 0) >= promo.get("max_uses", 1):
            return {"ok": False, "message": "Промокод исчерпан."}

        days = promo.get("days_granted", 0)
        requests = promo.get("requests_granted", 0)
        promo_until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days > 0 else None

        cursor.execute(
            _q("UPDATE users SET promo_code = ?, promo_until = ?, promo_requests_left = ? WHERE telegram_user_id = ?"),
            (promo_code, promo_until, requests if requests > 0 else None, telegram_user_id),
        )
        cursor.execute(
            _q("UPDATE promo_codes SET uses_count = uses_count + 1 WHERE code = ?"),
            (promo_code,),
        )
        connection.commit()

    return {"ok": True, "message": f"Промокод активирован! Дней: {days}, запросов: {requests}."}


def activate_subscription(telegram_user_id: int, days: int) -> None:
    """Активирует подписку на указанное количество дней."""
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("UPDATE users SET subscription_status = 'active', subscription_until = ? WHERE telegram_user_id = ?"),
            (until, telegram_user_id),
        )
        connection.commit()


def deactivate_expired_subscriptions() -> int:
    """Деактивирует истёкшие подписки. Возвращает количество деактивированных."""
    now_iso = utc_now()
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            _q("UPDATE users SET subscription_status = 'inactive' "
               "WHERE subscription_status = 'active' AND subscription_until IS NOT NULL AND subscription_until < ?"),
            (now_iso,),
        )
        count = cursor.rowcount
        connection.commit()
    return count