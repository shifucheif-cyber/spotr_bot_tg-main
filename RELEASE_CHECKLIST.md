# Release Checklist

Короткий чеклист для запуска после восстановления сети до Telegram и замены `GROQ_API_KEY`.

## 1. Конфигурация

- Проверить, что проект запускается через `d:/spotr_bot_tg-main/venv/Scripts/python.exe`.
- Обновить `GROQ_API_KEY` в `.env`.
- Убедиться, что в `.env` заполнены:
  - `TELEGRAM_TOKEN`
  - `GROQ_API_KEY`
  - `SAMBANOVA_API_KEY`
  - `SERPER_API_KEY`
  - `EXA_API_KEY`
  - `TAVILY_API_KEY`
- Не менять порядок fallback-провайдеров: `Groq -> SambaNova -> Google -> DeepSeek`.

## 2. Быстрые офлайн-проверки

Выполнить:

```powershell
d:/spotr_bot_tg-main/venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
```

Ожидаемо:

- все тесты зелёные
- ошибок импорта нет
- formatter/output pipeline не теряет `exact_score`, `total_prediction`, `analysis_summary`

## 3. Smoke по сервисам

Минимальный smoke:

```powershell
d:/spotr_bot_tg-main/venv/Scripts/python.exe _test_modules.py
```

Полный smoke:

```powershell
$env:SMOKE_PROFILE = "full"
d:/spotr_bot_tg-main/venv/Scripts/python.exe _test_modules.py
```

Ожидаемо:

- основные дисциплины дают непустой результат
- `data_router` проходит по ключевым веткам
- допустима деградация только по внешним источникам уровня `TheSportsDB`

## 4. E2E по хоккею

Выполнить:

```powershell
d:/spotr_bot_tg-main/venv/Scripts/python.exe _run_hockey_test.py
```

Ожидаемо:

- если `Groq` рабочий, ответ приходит через `Groq`
- если `Groq` снова недоступен, скрипт автоматически падает в `SambaNova`
- в `_hockey_analysis.txt` записан итоговый анализ

Если `Groq` отвечает `401 invalid_api_key`, это не сеть, а невалидный ключ.

## 5. Проверка Telegram-сети

Перед запуском бота убедиться, что с локальной машины снова доступен `api.telegram.org:443`.

Если при старте возникает:

- `TelegramNetworkError`
- `ClientConnectorError`
- `WinError 121`
- `WinError 1231`

значит проблема в сети/маршрутизации до Telegram, а не в LLM-провайдерах.

## 6. Запуск бота

Выполнить:

```powershell
d:/spotr_bot_tg-main/venv/Scripts/python.exe bot.py
```

Ожидаемо:

- процесс не завершается сразу
- нет ошибок на `delete_webhook`
- бот отвечает на `/start`

## 7. Ручной regression flow в Telegram

Пройти минимум такие сценарии:

1. `/start` -> `Футбол` -> две команды -> дата -> получить итоговый ответ.
2. `/start` -> `Киберспорт` -> `Counter-Strike 2` -> две команды -> дата -> получить итоговый ответ.
3. `/start` -> `Теннис` -> игроки одной строкой через `vs` -> дата.
4. Проверить длинный ответ: сообщение должно корректно дробиться на части.
5. Проверить fallback-поведение при отказе `Groq`: ответ должен прийти через `SambaNova`.

## 8. Критерии готовности

- офлайн test suite зелёный
- smoke проходит
- E2E проходит хотя бы через один рабочий LLM-провайдер
- бот стабильно стартует
- Telegram happy path проверен вручную

## 9. Что считать известными внешними рисками

- `TheSportsDB` может отдавать `404` или пустой результат
- отдельные поисковые источники могут деградировать по rate-limit или доступности
- Windows PowerShell/terminal bridge может искажать вывод команды, но это не влияет на фактический результат тестов