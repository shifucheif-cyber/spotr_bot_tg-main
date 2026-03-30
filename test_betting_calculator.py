"""Test for betting_calculator module"""
import sys
sys.path.insert(0, '/d/spotr_bot_tg-main')

from services.betting_calculator import (
    extract_probability,
    calculate_stake_percentage,
    format_stake_recommendation,
    get_bet_recommendation
)


def test_extract_probability():
    """Test probability extraction from various text formats"""
    
    test_cases = [
        # Pattern: "Вероятность победы (1-я команда): 75%"
        ("📊 **Вероятность победы (1-я команда):** 75%\n💰 **Рекомендация по ставке:**", 75.0),
        
        # Pattern: "P = 85%"
        ("За победу команды P = 85%", 85.0),
        
        # Pattern: "вероятность: 60%"
        ("Моя вероятность: 60%", 60.0),
        
        # Pattern: plain "%"
        ("Шанс выигрыша 92%", 92.0),
        
        # Pattern with decimal
        ("Вероятность: 67.5%", 67.5),
        
        # Multiple percentages - should get first one
        ("Вероятность 73% и уверенность 85%", 73.0),
        
        # No probability
        ("Анализ матча без вероятности", None),
    ]
    
    print("Testing extract_probability():")
    for text, expected in test_cases:
        result = extract_probability(text)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"  {status}: '{text[:50]}...' -> {result} (expected {expected})")
    print()


def test_calculate_stake_percentage():
    """Test stake calculation based on probability"""
    
    test_cases = [
        # P > 80% → 6%
        (85, 6),
        (100, 6),
        (81, 6),
        
        # 66% ≤ P ≤ 80% → 3%
        (75, 3),
        (66, 3),
        (80, 3),
        (70, 3),
        
        # 55% ≤ P ≤ 65% → 1%
        (55, 1),
        (60, 1),
        (65, 1),
        
        # P < 55% → None (skip)
        (54, None),
        (50, None),
        (30, None),
        (1, None),
    ]
    
    print("Testing calculate_stake_percentage():")
    for probability, expected in test_cases:
        result = calculate_stake_percentage(probability)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"  {status}: {probability}% -> {result}% stake (expected {expected}%)")
    print()


def test_format_stake_recommendation():
    """Test formatting of recommendations"""
    
    test_cases = [
        (85.0, 6),
        (75.0, 3),
        (60.0, 1),
        (50.0, None),
    ]
    
    print("Testing format_stake_recommendation():")
    for probability, stake in test_cases:
        result = format_stake_recommendation(probability, stake)
        print(f"  P={probability}%, Stake={stake}%:")
        print(f"    {result}")
    print()


def test_get_bet_recommendation():
    """Test full flow: LLM response -> probability -> stake"""
    
    llm_response = """
    📊 **АНАЛИЗ МАТЧА**
    
    Team A имеет очень сильную форму, выиграла последние 5 игр.
    Team B выглядит слабо, но не без шансов.
    
    📊 **Вероятность победы (1-я команда):** 78%
    
    Анализируя все факторы, рекомендую на Team A.
    """
    
    print("Testing get_bet_recommendation() (full flow):")
    probability, recommendation = get_bet_recommendation(llm_response)
    print(f"  Extracted probability: {probability}%")
    print(f"  Recommendation: {recommendation}")
    print()


if __name__ == "__main__":
    test_extract_probability()
    test_calculate_stake_percentage()
    test_format_stake_recommendation()
    test_get_bet_recommendation()
    
    print("=" * 60)
    print("✅ All tests completed!")
