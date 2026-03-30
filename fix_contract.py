import re

with open("bot.py", "r", encoding="utf-8") as f:
    text = f.read()

# I want to add `f"💡 Детали: {prediction_struct.get('recommendation', 'Нет данных')}",` exactly below `f"💰 Ставка: {stake_text}",`
target = 'f"💰 Ставка: {stake_text}",'
replacement = 'f"💰 Ставка: {stake_text}",\n        f"💡 Детали: {prediction_struct.get(\'recommendation\', \'Нет данных\')}",'

text = text.replace(target, replacement)

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(text)
print("done")
