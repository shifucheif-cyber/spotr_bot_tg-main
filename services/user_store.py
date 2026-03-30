import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("BOT_DB_PATH", BASE_DIR / "bot_data.sqlite3"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_user_store() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_user_id INTEGER PRIMARY KEY,
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
                last_match TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_time TEXT NOT NULL,
                details_json TEXT,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_events_user_time ON user_events(telegram_user_id, event_time)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_events_type_time ON user_events(event_type, event_time)"
        )
        connection.commit()


def upsert_user(user: Any, admin_telegram_id: Optional[int] = None) -> None:
    timestamp = utc_now()
    is_admin = int(bool(admin_telegram_id and user.id == admin_telegram_id))
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO users (
                telegram_user_id, username, first_name, last_name, first_seen, last_seen, is_admin
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen=excluded.last_seen,
                is_admin=excluded.is_admin
            """,
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
            f"UPDATE users SET {', '.join(parts)} WHERE telegram_user_id = ?",
            values,
        )
        connection.commit()


def log_user_event(user_id: int, event_type: str, details: Optional[Dict[str, Any]] = None) -> None:
    with closing(get_connection()) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO user_events (telegram_user_id, event_type, event_time, details_json) VALUES (?, ?, ?, ?)",
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
        total_users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_day = cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (day_ago,)).fetchone()[0]
        active_week = cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (week_ago,)).fetchone()[0]
        active_month = cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (month_ago,)).fetchone()[0]
        total_requests = cursor.execute("SELECT COALESCE(SUM(requests_count), 0) FROM users").fetchone()[0]
        total_analyses = cursor.execute("SELECT COALESCE(SUM(analyses_count), 0) FROM users").fetchone()[0]
        successful_analyses = cursor.execute("SELECT COALESCE(SUM(successful_analyses), 0) FROM users").fetchone()[0]
        active_subscriptions = cursor.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_status = 'active' AND (subscription_until IS NULL OR subscription_until >= ?)",
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
        rows = connection.execute(
            """
            SELECT telegram_user_id, username, first_name, last_name, last_seen,
                   requests_count, analyses_count, subscription_status, is_admin
            FROM users
            ORDER BY last_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_user_details(telegram_user_id: int) -> Optional[Dict[str, Any]]:
    with closing(get_connection()) as connection:
        user_row = connection.execute(
            "SELECT * FROM users WHERE telegram_user_id = ?",
            (telegram_user_id,),
        ).fetchone()
        if not user_row:
            return None

        event_rows = connection.execute(
            """
            SELECT event_type, event_time, details_json
            FROM user_events
            WHERE telegram_user_id = ?
            ORDER BY event_time DESC
            LIMIT 10
            """,
            (telegram_user_id,),
        ).fetchall()

    details = dict(user_row)
    details["recent_events"] = [dict(row) for row in event_rows]
    return details