import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "123456:TESTTOKEN")

import bot


class FakeState:
    def __init__(self, initial=None):
        self.data = dict(initial or {})
        self.last_state = None
        self.cleared = False

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.last_state = state

    async def clear(self):
        self.cleared = True
        self.data.clear()


class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_content_with_metadata_falls_back_to_sambanova(self):
        with patch.object(bot, "generate_with_groq", new=AsyncMock(side_effect=ValueError("bad groq key"))), \
             patch.object(bot, "generate_with_sambanova", new=AsyncMock(return_value="samba response")) as mocked_samba, \
             patch.object(bot, "generate_with_google", new=AsyncMock(return_value="google response")), \
             patch.object(bot, "generate_with_deepseek", new=AsyncMock(return_value="deepseek response")):
            result = await bot.generate_content_with_metadata("payload", "хоккей")

        self.assertEqual(result, {"provider": "sambanova", "text": "samba response"})
        mocked_samba.assert_awaited_once_with("payload", "хоккей", None)

    async def test_generate_content_with_metadata_raises_when_all_providers_fail(self):
        with patch.object(bot, "generate_with_groq", new=AsyncMock(side_effect=ValueError("groq failed"))), \
             patch.object(bot, "generate_with_sambanova", new=AsyncMock(side_effect=ValueError("samba failed"))), \
             patch.object(bot, "generate_with_google", new=AsyncMock(side_effect=ValueError("google failed"))), \
             patch.object(bot, "generate_with_deepseek", new=AsyncMock(side_effect=ValueError("deepseek failed"))):
            with self.assertRaises(ValueError) as exc:
                await bot.generate_content_with_metadata("payload", "хоккей")

        self.assertIn("deepseek failed", str(exc.exception))

    async def test_set_discipline_routes_hierarchical_branch_to_subdiscipline(self):
        state = FakeState()
        message = SimpleNamespace(text="киберспорт", answer=AsyncMock())

        await bot.set_discipline(message, state)

        self.assertEqual(state.data["discipline"], "киберспорт")
        self.assertEqual(state.last_state, bot.OrderAnalysis.waiting_subdiscipline)
        message.answer.assert_awaited_once()

    async def test_set_discipline_routes_direct_branch_to_team1(self):
        state = FakeState()
        message = SimpleNamespace(text="Футбол", answer=AsyncMock())

        await bot.set_discipline(message, state)

        self.assertEqual(state.data["discipline"], "футбол")
        self.assertEqual(state.last_state, bot.OrderAnalysis.waiting_team1)
        message.answer.assert_awaited_once()

    async def test_set_team1_accepts_inline_match_and_moves_to_date(self):
        state = FakeState({"discipline": "футбол"})
        message = SimpleNamespace(text="Зенит vs ЦСКА", answer=AsyncMock())
        resolved_match = {
            "team1": {"corrected": "Зенит"},
            "team2": {"corrected": "ЦСКА"},
            "match": "Зенит vs ЦСКА",
        }

        with patch.object(bot, "split_match_text", return_value=["Зенит", "ЦСКА"]), \
             patch.object(bot, "resolve_entity_name", side_effect=[
                 {"original": "Зенит", "corrected": "Зенит", "applied": False},
                 {"original": "ЦСКА", "corrected": "ЦСКА", "applied": False},
             ]), \
             patch.object(bot, "resolve_match_entities", return_value=resolved_match), \
             patch.object(bot, "get_date_keyboard", return_value="keyboard"):
            await bot.set_team1(message, state)

        self.assertEqual(state.data["team1"], "Зенит")
        self.assertEqual(state.data["team2"], "ЦСКА")
        self.assertEqual(state.last_state, bot.OrderAnalysis.waiting_date)
        message.answer.assert_awaited_once()

    async def test_fetch_match_data_returns_timeout_fallback_payload(self):
        with patch.object(bot, "get_match_data", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            payload, raw_data = await bot.fetch_match_data(
                "Зенит vs ЦСКА",
                "футбол",
                {"date": "10.04.26"},
                "Матч подтвержден",
            )

        self.assertIn("Сбор данных затянулся", raw_data)
        self.assertIn("Матч подтвержден", payload)
        self.assertIn("Зенит", payload)
        self.assertIn("ЦСКА", payload)

    async def test_resolve_match_validation_returns_validated_match(self):
        validated = {
            "status": "validated",
            "match": {"sport": "football", "home": "Зенит", "away": "ЦСКА", "date": "10.04.26", "league": "РПЛ"},
            "report": "validated report",
            "region": "ru",
        }

        with patch.object(bot, "validate_match_request", return_value=validated):
            found, report, valid, sources = await bot.resolve_match_validation("Зенит", "ЦСКА", "10.04.26", "футбол")

        self.assertTrue(valid)
        self.assertEqual(report, "validated report")
        self.assertEqual(found["region"], "ru")

    async def test_handle_date_starts_analysis_for_valid_match(self):
        state = FakeState({"team1": "Зенит", "team2": "ЦСКА", "discipline": "футбол"})
        message = SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock())
        callback = SimpleNamespace(data="date_10.04.26", answer=AsyncMock(), message=message, from_user=SimpleNamespace(id=123))
        found_match = {"home": "Зенит", "away": "ЦСКА", "date": "10.04.26", "league": "РПЛ"}

        with patch.object(bot, "resolve_match_validation", new=AsyncMock(return_value=(found_match, "report", True, []))), \
             patch.object(bot, "format_match_confirmation", return_value="confirmed"), \
             patch.object(bot, "start_analysis", new=AsyncMock()) as mocked_analysis:
            await bot.handle_date(callback, state)

        callback.answer.assert_awaited_once()
        message.edit_text.assert_awaited_once_with("📅 Дата: 10.04.26")
        message.answer.assert_awaited_once_with("confirmed")
        self.assertEqual(state.data["date"], "10.04.26")
        self.assertEqual(state.data["found_match"], found_match)
        self.assertEqual(state.data["clarification_type"], "ok")
        mocked_analysis.assert_awaited_once_with(message, state, user_id=123, real_user=callback.from_user)


    async def test_premium_disabled_when_no_paywall(self):
        with patch.object(bot, "ENABLE_PAYWALL", False):
            message = SimpleNamespace(answer=AsyncMock())
            await bot.premium(message)
        message.answer.assert_awaited_once()
        self.assertIn("в разработке", message.answer.call_args[0][0])

    async def test_promo_disabled_when_no_paywall(self):
        with patch.object(bot, "ENABLE_PAYWALL", False):
            message = SimpleNamespace(answer=AsyncMock(), text="/promo CODE", from_user=SimpleNamespace(id=1))
            await bot.promo_command(message)
        message.answer.assert_awaited_once()
        self.assertIn("в разработке", message.answer.call_args[0][0])

    async def test_start_keyboard_has_promo_premium_when_paywall(self):
        with patch.object(bot, "ENABLE_PAYWALL", True), \
             patch.object(bot, "check_daily_limit", return_value=True), \
             patch.object(bot, "touch_user"):
            message = SimpleNamespace(
                answer=AsyncMock(),
                from_user=SimpleNamespace(id=1, username="u", first_name="F", last_name="L"),
            )
            state = FakeState()
            await bot.start(message, state)
        call_args = message.answer.call_args
        kb = call_args[1]["reply_markup"].keyboard
        first_row_texts = [btn.text for btn in kb[0]]
        self.assertIn("🎁 Промо (free)", first_row_texts)
        self.assertIn("⭐ Премиум", first_row_texts)


if __name__ == "__main__":
    unittest.main()