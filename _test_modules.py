"""Smoke test for current service architecture."""

import asyncio
import os
import sys

os.environ.setdefault("APP_LOG_LEVEL", "WARNING")
os.environ.setdefault("EXTERNAL_LOG_LEVEL", "ERROR")
SMOKE_PROFILE = os.getenv("SMOKE_PROFILE", "minimal").strip().lower()


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding)


async def run_case(name, coro, *args, timeout=45):
    try:
        result = await asyncio.wait_for(coro(*args), timeout=timeout)
    except asyncio.CancelledError:
        print(_console_safe(f"  [{name}] CANCELLED"))
        return False
    except asyncio.TimeoutError:
        print(_console_safe(f"  [{name}] TIMEOUT (>{timeout}s)"))
        return False
    except Exception as exc:
        print(_console_safe(f"  [{name}] ERROR: {type(exc).__name__}: {exc}"))
        return False

    if not result:
        print(_console_safe(f"  [{name}] FAIL - empty/None result"))
        return False

    preview = result.replace("\n", " ")[:160]
    status = "OK" if len(result) > 50 else "WARN"
    print(_console_safe(f"  [{name}] {status} - {len(result)} chars: {preview}"))
    return True


async def main():
    ctx = {"date": "2026-04-10", "league": "", "sport": "", "home": "", "away": ""}

    print("=== DISCIPLINE SERVICES ===")
    from services.basketball_service import get_basketball_data
    from services.cs2_service import get_esports_data
    from services.football_service import get_football_data
    from services.hockey_service import get_hockey_data
    from services.mma_service import get_mma_data
    from services.table_tennis_service import get_table_tennis_data
    from services.tennis_service import get_tennis_data
    from services.volleyball_service import get_volleyball_data

    minimal_service_cases = [
        ("football", get_football_data, "Real Madrid vs Barcelona", ctx),
        ("hockey", get_hockey_data, "CSKA vs SKA", ctx),
        ("cs2", get_esports_data, "Navi vs FaZe", "cs2", ctx),
        ("tennis", get_tennis_data, "Djokovic vs Alcaraz", "tennis", ctx),
    ]
    full_only_service_cases = [
        ("basketball", get_basketball_data, "Lakers vs Celtics", ctx),
        ("table_tennis", get_table_tennis_data, "Ma Long vs Fan Zhendong", ctx),
        ("mma", get_mma_data, "Makhachev vs Oliveira", "mma", ctx),
        ("boxing", get_mma_data, "Tyson Fury vs Usyk", "boxing", ctx),
        ("volleyball", get_volleyball_data, "Zenit Kazan vs Dinamo Moscow", ctx),
        ("dota2", get_esports_data, "Team Spirit vs Tundra", "dota2", ctx),
        ("lol", get_esports_data, "T1 vs JDG", "lol", ctx),
        ("valorant", get_esports_data, "Sentinels vs Fnatic", "valorant", ctx),
    ]
    service_cases = minimal_service_cases if SMOKE_PROFILE != "full" else minimal_service_cases + full_only_service_cases

    results = []
    for case in service_cases:
        results.append(await run_case(*case))

    print("\n=== DATA ROUTER ===")
    from data_router import get_match_data

    minimal_router_cases = [
        ("router:football", get_match_data, "Real Madrid vs Barcelona", "футбол", ctx),
        ("router:cs2", get_match_data, "Navi vs FaZe", "киберспорт cs2", ctx),
    ]
    full_only_router_cases = [
        ("router:hockey", get_match_data, "CSKA vs SKA", "хоккей", ctx),
        ("router:boxing", get_match_data, "Tyson Fury vs Usyk", "бокс", ctx),
    ]
    router_cases = minimal_router_cases if SMOKE_PROFILE != "full" else minimal_router_cases + full_only_router_cases
    for case in router_cases:
        results.append(await run_case(*case))

    print(f"\n=== PROFILE: {SMOKE_PROFILE} ===")
    print("\n=== EXTERNAL SOURCE ===")
    from services.external_source import search_event_thesportsdb

    try:
        event = await asyncio.to_thread(search_event_thesportsdb, "Real Madrid vs Barcelona")
        if event:
            print(_console_safe(f"  [thesportsdb] OK - got event: {event.get('strEvent', 'unknown')}"))
            results.append(True)
        else:
            print("  [thesportsdb] WARN - no event found or API unavailable")
            results.append(False)
    except Exception as exc:
        print(_console_safe(f"  [thesportsdb] ERROR: {type(exc).__name__}: {exc}"))
        results.append(False)

    passed = sum(1 for item in results if item)
    total = len(results)
    print(f"\nDONE — passed {passed}/{total}")


if __name__ == "__main__":
    asyncio.run(main())
