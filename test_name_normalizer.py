import sys

sys.path.insert(0, "d:\\spotr_bot_tg-main")

from services.name_normalizer import expand_context_terms, get_search_variants, resolve_entity_name, resolve_match_entities, split_match_text


def test_name_normalizer() -> bool:
    checks = [
        (split_match_text("Team A против Team B"), ["Team A", "Team B"]),
        (resolve_entity_name("Автомибилист", discipline="хоккей")["corrected"], "Автомобилист"),
        (resolve_entity_name("Man Utd", discipline="футбол")["corrected"], "Manchester United"),
        (resolve_entity_name("Natus Vincere", discipline="киберспорт")["corrected"], "Navi"),
        (resolve_entity_name("GenG", discipline="lol")["corrected"], "Gen.G"),
        (resolve_entity_name("PRX", discipline="valorant")["corrected"], "Paper Rex"),
        (resolve_match_entities("Автомибилист", "Салават", discipline="хоккей")["match"], "Автомобилист vs Салават Юлаев"),
        (get_search_variants("Natus Vincere", discipline="cs2")[:2], ["Natus Vincere", "Navi"]),
        (expand_context_terms("VCT", discipline="valorant")[:2], ["VCT", "Valorant Champions Tour"]),
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
    raise SystemExit(0 if test_name_normalizer() else 1)