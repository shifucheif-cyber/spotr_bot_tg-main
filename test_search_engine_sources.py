import sys

sys.path.insert(0, "d:\\spotr_bot_tg-main")

from services.search_engine import _get_sites_for_query


def test_source_priority() -> bool:
    checks = [
        (
            _get_sites_for_query("football", "Спартак", "Зенит")[:4],
            ["premierliga.ru", "soccer.ru", "sports.ru", "rustat.pro"],
        ),
        (
            _get_sites_for_query("football", "Спартак", "РПЛ 2026")[:4],
            ["premierliga.ru", "soccer.ru", "sports.ru", "rustat.pro"],
        ),
        (
            _get_sites_for_query("hockey", "Авангард", "КХЛ плей-офф")[:3],
            ["khl.ru", "allhockey.ru", "r-hockey.ru"],
        ),
        (
            _get_sites_for_query("football", "Зенит", "Fenerbahce")[:2],
            ["whoscored.com", "transfermarkt.com"],
        ),
        (
            _get_sites_for_query("basketball", "Зенит", "Единая лига ВТБ")[:2],
            ["vtb-league.com", "basketball-reference.com"],
        ),
        (
            _get_sites_for_query("cs2", "Team Spirit", "СНГ квалификация")[:2],
            ["cyber.sports.ru", "cybersport.ru"],
        ),
        (
            _get_sites_for_query("football", "Manchester United", "Premier League")[:2],
            ["whoscored.com", "transfermarkt.com"],
        ),
    ]

    all_passed = True
    for actual, expected in checks:
        if actual != expected:
            all_passed = False
            print(f"FAIL: expected={expected!r} actual={actual!r}")
        else:
            print(f"PASS: {expected!r}")

    return all_passed


if __name__ == "__main__":
    raise SystemExit(0 if test_source_priority() else 1)