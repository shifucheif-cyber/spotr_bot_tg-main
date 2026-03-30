"""Betting recommendation calculator based on probability thresholds"""
import re


def extract_probability(llm_response: str) -> float | None:
    """
    Extracts probability percentage from LLM response.
    
    Looks for patterns like:
    - "Вероятность победы (1-я команда): 75%"
    - "P = 75%"
    - "вероятность: 75%"
    - Any number followed by %
    """
    # Try pattern: "Вероятность ... : X%"
    match = re.search(r'Вероятность[^:]*:\s*(\d+(?:[.,]\d+)?)\s*%', llm_response, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', '.'))
    
    # Try pattern: "P = X%"
    match = re.search(r'[Пп]\s*[=:]\s*(\d+(?:[.,]\d+)?)\s*%', llm_response)
    if match:
        return float(match.group(1).replace(',', '.'))
    
    # Try pattern: "вероятность: X%"
    match = re.search(r'вероятность[^:]*:\s*(\d+(?:[.,]\d+)?)\s*%', llm_response, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', '.'))
    
    # Last resort: find any percentage in the text
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', llm_response)
    if match:
        return float(match.group(1).replace(',', '.'))
    
    return None


def calculate_stake_percentage(probability: float) -> int | None:
    """
    Calculates recommended stake percentage based on probability threshold.
    
    Formula:
    - P > 80% → 6% of bankroll (Ultra-confidence, "Sure thing")
    - 66% ≤ P ≤ 80% → 3% of bankroll (High probability)
    - 55% ≤ P ≤ 65% → 1% of bankroll (Risky bet/Value bet)
    - P < 55% → None (Don't bet, too uncertain)
    
    Args:
        probability: Probability percentage (0-100)
    
    Returns:
        Stake percentage (1, 3, 6) or None if skip recommendation
    """
    if probability > 80:
        return 6
    elif 66 <= probability <= 80:
        return 3
    elif 55 <= probability <= 65:
        return 1
    else:
        return None


def format_stake_recommendation(probability: float, stake_percent: int | None) -> str:
    """
    Formats stake recommendation for user display.
    
    Args:
        probability: Probability percentage
        stake_percent: Recommended stake percentage or None
    
    Returns:
        Formatted recommendation string
    """
    if stake_percent is None:
        return (
            f"⚠️ **РЕКОМЕНДАЦИЯ:** Вероятность {probability:.0f}% — "
            f"**ПРОПУСТИТЬ СОБЫТИЕ** (слишком высокая неопределённость)"
        )
    
    confidence_level = ""
    if probability > 80:
        confidence_level = "Ультра-уверенность"
    elif 66 <= probability <= 80:
        confidence_level = "Высокая вероятность"
    else:
        confidence_level = "Рискованно/Валуй"
    
    return (
        f"💰 **РЕКОМЕНДАЦИЯ:** {stake_percent}% от вашего банка "
        f"(вероятность {probability:.0f}% = {confidence_level})"
    )


def get_bet_recommendation(llm_response: str) -> dict:
    """
    Main function: extracts probability from LLM response and calculates recommendation.
    Enforced structure: returns a dict with explicit fields, not a tuple.
    
    Args:
        llm_response: Text response from LLM
    
    Returns:
        Dict with fields:
        - probability: float or None
        - stake_percent: int or None (6, 3, 1)
        - recommendation: str (formatted text)
        - status: "success" or "invalid"
    """
    probability = extract_probability(llm_response)
    
    if probability is None:
        return {
            "probability": None,
            "stake_percent": None,
            "recommendation": "Вероятность не указана",
            "status": "invalid",
        }
    
    # Clamp probability to 0-100%
    probability = max(0, min(100, probability))
    
    stake_percent = calculate_stake_percentage(probability)
    recommendation = format_stake_recommendation(probability, stake_percent)
    
    return {
        "probability": probability,
        "stake_percent": stake_percent,
        "recommendation": recommendation,
        "status": "success",
    }
