"""Функциональный тест всех модулей бота."""
import asyncio
import os
import sys

# Минимальный .env fallback если ключи не в env
os.environ.setdefault("APP_LOG_LEVEL", "WARNING")
os.environ.setdefault("EXTERNAL_LOG_LEVEL", "ERROR")


async def test_module(name, coro_fn, *args):
    try:
        result = await asyncio.wait_for(coro_fn(*args), timeout=60)
        if result and len(result) > 50:
            print(f"  [{name}] OK — {len(result)} chars")
        elif result:
            print(f"  [{name}] WARN (short) — {len(result)} chars: {result[:200]}")
        else:
            print(f"  [{name}] FAIL — empty/None result")
    except asyncio.TimeoutError:
        print(f"  [{name}] TIMEOUT (>60s)")
    except Exception as e:
        print(f"  [{name}] ERROR: {type(e).__name__}: {e}")


async def main():
    ctx = {"date": "2026-04-10", "league": "", "sport": "", "home": "", "away": ""}

    print("=== DISCIPLINE SERVICES ===")

    from services.football_service import get_football_data
    await test_module("football", get_football_data, "Real Madrid vs Barcelona", ctx)

    from services.hockey_service import get_hockey_data
    await test_module("hockey", get_hockey_data, "CSKA vs SKA", ctx)

    from services.basketball_service import get_basketball_data
    await test_module("basketball", get_basketball_data, "Lakers vs Celtics", ctx)

    from services.tennis_service import get_tennis_data
    await test_module("tennis", get_tennis_data, "Djokovic vs Alcaraz", "tennis", ctx)

    from services.table_tennis_service import get_table_tennis_data
    await test_module("table_tennis", get_table_tennis_data, "Ma Long vs Fan Zhendong", ctx)

    from services.mma_service import get_mma_data
    await test_module("mma", get_mma_data, "Makhachev vs Oliveira", "mma", ctx)
    await test_module("boxing", get_mma_data, "Tyson Fury vs Usyk", "boxing", ctx)

    from services.volleyball_service import get_volleyball_data
    await test_module("volleyball", get_volleyball_data, "Zenit Kazan vs Dinamo Moscow", ctx)

    from services.cs2_service import get_esports_data
    await test_module("cs2", get_esports_data, "Navi vs FaZe", "cs2")
    await test_module("dota2", get_esports_data, "Team Spirit vs Tundra", "dota2")
    await test_module("lol", get_esports_data, "T1 vs JDG", "lol")
    await test_module("valorant", get_esports_data, "Sentinels vs Fnatic", "valorant")

    print("\n=== DATA ROUTER ===")
    from data_router import get_match_data
    await test_module("router:football", get_match_data, "Real Madrid vs Barcelona", "футбол", ctx)

    print("\n=== EXTERNAL SOURCE ===")
    from services.external_source import search_event_thesportsdb
    try:
        r = search_event_thesportsdb("Real Madrid vs Barcelona")
        if r:
            print(f"  [thesportsdb] OK — got event: {r.get('strEvent', 'unknown')}")
        else:
            print("  [thesportsdb] None (no event found or API down)")
    except Exception as e:
        print(f"  [thesportsdb] ERROR: {type(e).__name__}: {e}")

    print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
