with open("bot.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('stake_text = f"{stake}%" if stake is not None else "ПРОПУСК"', 'stake_text = str(stake) if stake is not None else "ПРОПУСК"')

import re
# check if also "recommendation" string is rendered.
# Wait, format_response_contract might not use "recommendation" inside it?

with open("bot.py", "w", encoding="utf-8") as f:
    f.write(text)
print("done")
