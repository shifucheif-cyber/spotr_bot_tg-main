# Release Checklist

Короткий чеклист для запуска после восстановления сети до Telegram и замены `GROQ_API_KEY`.

> **Пути:** на Windows используйте `venv\Scripts\python.exe`, на Linux/macOS — `venv/bin/python`. Ниже используется `python` — подразумевается Python из активированного venv.

## 1. Конфигурация

- Проверить, что Python запускается из виртуального окружения (`python --version`).
- Обновить `GROQ_API_KEY` в `.env`.
- Убедиться, что в `.env` заполнены:
  - `TELEGRAM_TOKEN`
  - `DATABASE_URL` (PostgreSQL, обязательно для production)
  - `GROQ_API_KEY`
  - `SAMBANOVA_API_KEY`
  - `SERPER_API_KEY`
  - `EXA_API_KEY`
  - `TAVILY_API_KEY`
- Для локальной разработки без PostgreSQL: добавить `DB_BACKEND=sqlite`
- Не менять порядок fallback-провайдеров: `Groq -> SambaNova -> Google -> DeepSeek`.

## 2. Preflight-проверка окружения

Выполнить:

```bash
python preflight_check.py
```

Ожидаемо:

- статус `PASS` или `WARN`
- при `FAIL` — исправить указанные проблемы до продолжения
- при `WARN` — допустимо продолжать, если недоступные провайдеры не критичны

## 3. Быстрые офлайн-проверки

Выполнить:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Ожидаемо:

- все тесты зелёные
- ошибок импорта нет
- formatter/output pipeline не теряет `exact_score`, `total_prediction`, `analysis_summary`

## 4. Smoke по сервисам

Минимальный smoke:

```bash
python _test_modules.py
```

Полный smoke:

```bash
SMOKE_PROFILE=full python _test_modules.py
```

Ожидаемо:

- основные дисциплины дают непустой результат
- `data_router` проходит по ключевым веткам
- допустима деградация только по внешним источникам уровня `TheSportsDB`

## 5. E2E по хоккею

Выполнить:

```bash
python _run_hockey_test.py
```

Ожидаемо:

- если `Groq` рабочий, ответ приходит через `Groq`
- если `Groq` снова недоступен, скрипт автоматически падает в `SambaNova`
- в `_hockey_analysis.txt` записан итоговый анализ

Если `Groq` отвечает `401 invalid_api_key`, это не сеть, а невалидный ключ.

## 6. Проверка Telegram-сети

Перед запуском бота убедиться, что с машины доступен `api.telegram.org:443`.

Если при старте возникает:

- `TelegramNetworkError`
- `ClientConnectorError`
- `WinError 121` / `WinError 1231` (Windows)
- `ConnectionRefusedError` / `OSError` (Linux)

значит проблема в сети/маршрутизации до Telegram, а не в LLM-провайдерах.

## 7. Запуск бота

Выполнить:

```bash
python bot.py
```

Ожидаемо:

- процесс не завершается сразу
- нет ошибок на `delete_webhook`
- бот отвечает на `/start`

## 8. Ручной regression flow в Telegram

Пройти минимум такие сценарии:

1. `/start` -> `Футбол` -> две команды -> дата -> получить итоговый ответ.
2. `/start` -> `Киберспорт` -> `Counter-Strike 2` -> две команды -> дата -> получить итоговый ответ.
3. `/start` -> `Теннис` -> игроки одной строкой через `vs` -> дата.
4. Проверить длинный ответ: сообщение должно корректно дробиться на части.
5. Проверить fallback-поведение при отказе `Groq`: ответ должен прийти через `SambaNova`.

## 9. Критерии готовности

- офлайн test suite зелёный
- smoke проходит
- E2E проходит хотя бы через один рабочий LLM-провайдер
- бот стабильно стартует
- Telegram happy path проверен вручную

## 10. Что считать известными внешними рисками

- `TheSportsDB` может отдавать `404` или пустой результат
- отдельные поисковые источники могут деградировать по rate-limit или доступности
- PowerShell/terminal bridge может искажать вывод команды, но это не влияет на фактический результат тестов

## 11. База данных и ограничения (paywall)

- Убедитесь, что выставлен DB_BACKEND (sqlite или postgres).
- Если postgres, установите переменную DATABASE_URL и зависимость psycopg2-binary.
- При вызове init_user_store() автоматически создаются столбцы daily_requests и last_request_date.
- Для включения дневного лимита и платных подписок, установите ENABLE_PAYWALL = True в bot.py перед запуском.
- Реализуйте команду /premium для оплаты и связи с админом для пользователей.
