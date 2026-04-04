import re
import json
import logging
from services.name_normalizer import split_match_text

logger = logging.getLogger(__name__)

def _extract_contract_field(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" -*")
    return ""


def _sanitize_side_summary(text: str) -> str:
    """Убирает из сводки по команде хвосты с датой/следующими блоками (артефакты regex)."""
    if not text:
        return ""
    t = text.strip()
    for marker in (
        "\n📅", "\n🏆", "\n📈", "\n🔢", "\n💰", "\n📋", "\n📝", "\n•", "\n- **",
        "\n\n",
    ):
        i = t.find(marker)
        if 0 < i < len(t):
            t = t[:i].strip()
    for marker in ("📅", "**Дата:**", "Дата матча", "Победитель:", "Прогноз по сч"):
        i = t.find(marker)
        if i >= 0:
            t = t[:i].strip()
    # «vs соперник» как целая сводка — не аналитика
    t = re.sub(r"(?i)^vs\.?\s+\S+(?:\s+\S+)?\s*$", "", t).strip()
    t = re.sub(r"(?i)^vs\.?\s+", "", t).strip()
    if len(t) > 250:
        t = t[:247] + "..."
    return t


def format_response_contract(match_text: str, raw_analysis: str, prediction_struct: dict) -> str:
    """
    Format final response as a brief prognosis card.
    Extracts short summaries per participant + key prediction fields.
    No full analysis text — only concise output for the user.
    """
    # Strip JSON blocks from raw analysis (internal data, not for user)
    cleaned_analysis = re.sub(r'(?i)```json\s*\{.*?\}\s*```', '', raw_analysis, flags=re.DOTALL).strip()
    cleaned_analysis = re.sub(r'(?i)\{\s*"win_probability_team1".*?\}', '', cleaned_analysis, flags=re.DOTALL).strip()
    cleaned_analysis = re.sub(r'(?i)\{\s*"winner".*?\}', '', cleaned_analysis, flags=re.DOTALL).strip()

    prob = prediction_struct.get("probability")
    stake = prediction_struct.get("stake_percent")
    
    winner = _extract_contract_field(cleaned_analysis, [r"Победитель:\s*(.+)", r"Исход:\s*(.+)", r"Прогноз победителя:\s*(.+)"])
    score = _extract_contract_field(cleaned_analysis, [r"Прогноз по счету:\s*(.+)", r"Прогноз по сч[её]ту / картам / сетам:\s*(.+)", r"Сч[её]т:\s*(.+)"])
    total = _extract_contract_field(cleaned_analysis, [r"Тотал:\s*(.+)", r"Total:\s*(.+)", r"Тотал карт:\s*(.+)", r"Total maps:\s*(.+)"])

    # Extract per-participant summaries from LLM output (1-2 sentences each)
    sides = split_match_text(match_text)
    side1_summary = ""
    side2_summary = ""
    if len(sides) == 2:
        for side_idx, (side, _target) in enumerate([(sides[0], "side1_summary"), (sides[1], "side2_summary")]):
            escaped = re.escape(side)
            # Сначала привязка к началу строки / буллету — иначе цеплялось «колорадо» внутри чужого абзаца и дата
            patterns = [
                rf"(?m)(?:^|\n)\s*[•\-]\s*\*{{0,2}}\[?{escaped}\]?\*{{0,2}}\s*[:：]\s*(.+?)(?=\n\s*[•\-📈🏆📊📋💰🔢📅]|\n\n|\Z)",
                rf"(?m)(?:^|\n)\s*\*{{0,2}}\[?{escaped}\]?\*{{0,2}}\s*[:：]\s*(.+?)(?=\n\s*[•\-📈🏆📊📋💰🔢📅]|\n\n|\Z)",
                rf"(?m)(?:^|\n)\s*📝\s*\*\*\[?{escaped}\]?\*\*\s*[:：]\s*(.+?)(?=\n\s*[•\-📈🏆📊📋💰🔢📅📝]|\n\n|\Z)",
            ]
            for pattern in patterns:
                m = re.search(pattern, cleaned_analysis, re.I | re.S)
                if m:
                    text = m.group(1).strip()
                    sentences = re.split(r"(?<=[.!?])\s+", text)
                    text = " ".join(sentences[:2]).strip()
                    text = _sanitize_side_summary(text)
                    if len(text) < 12:
                        continue
                    if side_idx == 0:
                        side1_summary = text
                    else:
                        side2_summary = text
                    break

    prob_text = f"{prob:.0f}%" if prob is not None else "не определена"
    stake_text = str(stake) if stake is not None else "ПРОПУСК"
    
    lines = [f"📊 **Матч:** {match_text}", ""]
    if total:
        lines.append(f"🎯 **Тотал:** {total}")
    if side1_summary and len(sides) == 2:
        lines.append(f"• **{sides[0]}:** {side1_summary}")
    if side2_summary and len(sides) == 2:
        lines.append(f"• **{sides[1]}:** {side2_summary}")
    if side1_summary or side2_summary:
        lines.append("")
    lines += [
        f"🏆 **Победитель:** {winner or '?'}",
        f"📈 **Вероятность:** {prob_text}",
        f"🔢 **Счёт:** {score or '?'}",
        f"💰 **Ставка:** {stake_text}",
        f"💡 {prediction_struct.get('recommendation', '')}",
    ]
    
    return "\n".join(lines)


def split_long_message(text: str, max_length: int = 4000) -> list[str]:
    """Разбивает большое сообщение на части (лимит Telegram - 4096)"""
    if len(text) <= max_length:
        return [text]
    
    messages = []
    current = ""
    
    # Разбиваем по абзацам
    paragraphs = text.split("\n\n")
    
    for para in paragraphs:
        # Если один абзац длиннее лимита — режем по строкам
        if len(para) > max_length:
            if current:
                messages.append(current)
                current = ""
            lines = para.split("\n")
            for line in lines:
                if len(current) + len(line) + 1 > max_length:
                    if current:
                        messages.append(current)
                    current = ""
                current += line + "\n"
            continue
        if len(current) + len(para) + 2 > max_length:
            if current:
                messages.append(current)
                current = ""
        current += para + "\n\n"
    
    if current:
        messages.append(current)
    
    return [msg.strip() for msg in messages if msg.strip()]


def format_prediction_response(analysis_match: str, raw_response: str) -> str:
    """Форматирует ответ от LLM в финальный вид для пользователя."""
    from services.betting_calculator import get_bet_recommendation
    prediction_struct = get_bet_recommendation(raw_response)
    return format_response_contract(analysis_match, raw_response, prediction_struct)
