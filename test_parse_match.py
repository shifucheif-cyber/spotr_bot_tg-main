"""Test for parse_match_sides function with "против" support"""
import sys
import re
sys.path.insert(0, 'd:\\spotr_bot_tg-main')

from bot import parse_match_sides


def test_parse_match_sides():
    """Test various match formats with vs, v, против, and -"""
    
    test_cases = [
        # "vs" format
        ("Team A vs Team B", ["Team A", "Team B"]),
        ("Team A vs. Team B", ["Team A", "Team B"]),
        ("FaZe vs Vitality", ["FaZe", "Vitality"]),
        
        # "v" format (short)
        ("Team A v Team B", ["Team A", "Team B"]),
        ("Team A v. Team B", ["Team A", "Team B"]),
        
        # "против" format (Russian) - NEW!
        ("Team A против Team B", ["Team A", "Team B"]),
        ("Team A ПРОТИВ Team B", ["Team A", "Team B"]),
        ("Команда А против Команда Б", ["Команда А", "Команда Б"]),
        ("фази против витальности", ["фази", "витальности"]),
        ("Автомибилист против Салават", ["Автомибилист", "Салават"]),
        
        # "-" format
        ("Team A - Team B", ["Team A", "Team B"]),
        ("Team A- Team B", ["Team A", "Team B"]),
        ("Team A -Team B", ["Team A", "Team B"]),
        
        # Case sensitivity
        ("Team A VS Team B", ["Team A", "Team B"]),
        ("Team A Vs Team B", ["Team A", "Team B"]),
        ("Team A VS. Team B", ["Team A", "Team B"]),
        
        # Extra spaces
        ("Team A  vs  Team B", ["Team A", "Team B"]),
        ("Team A  против  Team B", ["Team A", "Team B"]),
        
        # Single team (error case)
        ("Team A", ["Team A"]),
        
        # More separators
        ("Team A v Team B", ["Team A", "Team B"]),
        
        # With titles/ranks
        ("Real Madrid vs Barcelona", ["Real Madrid", "Barcelona"]),
        ("Real Madrid против Barcelona", ["Real Madrid", "Barcelona"]),
    ]
    
    print("Testing parse_match_sides():\n")
    
    all_passed = True
    for match_text, expected in test_cases:
        result = parse_match_sides(match_text)
        passed = result == expected
        status = "✅ PASS" if passed else "❌ FAIL"
        
        if not passed:
            all_passed = False
            print(f"{status}: '{match_text}'")
            print(f"  Expected: {expected}")
            print(f"  Got:      {result}")
        else:
            print(f"{status}: '{match_text}' -> {result}")
    
    print(f"\n{'='*60}")
    print(f"{'✅ All tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed


if __name__ == "__main__":
    success = test_parse_match_sides()
    sys.exit(0 if success else 1)
