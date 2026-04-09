import unittest
from unittest.mock import AsyncMock, patch

import data_router


class DataRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_table_tennis_before_generic_tennis(self):
        with patch.object(data_router, "get_table_tennis_data", new=AsyncMock(return_value="tt-result")) as mocked_table_tennis:
            result = await data_router.get_match_data("A vs B", "настольный теннис", {"date": "2026-04-10"})

        self.assertEqual(result, "tt-result")
        mocked_table_tennis.assert_awaited_once_with("A vs B", match_context={"date": "2026-04-10"})

    async def test_routes_esports_with_original_discipline(self):
        with patch.object(data_router, "get_esports_data", new=AsyncMock(return_value="cs2-result")) as mocked_esports:
            result = await data_router.get_match_data("Navi vs FaZe", "киберспорт cs2", {"league": "Major"})

        self.assertEqual(result, "cs2-result")
        mocked_esports.assert_awaited_once_with("Navi vs FaZe", "киберспорт cs2", match_context={"league": "Major"})

    async def test_routes_boxing_before_mma(self):
        with patch.object(data_router, "get_mma_data", new=AsyncMock(return_value="boxing-result")) as mocked_mma:
            result = await data_router.get_match_data("Fury vs Usyk", "boxing", {"date": "2026-04-10"})

        self.assertEqual(result, "boxing-result")
        mocked_mma.assert_awaited_once_with("Fury vs Usyk", subdiscipline="boxing", match_context={"date": "2026-04-10"})

    async def test_routes_mma_branch(self):
        with patch.object(data_router, "get_mma_data", new=AsyncMock(return_value="mma-result")) as mocked_mma:
            result = await data_router.get_match_data("Makhachev vs Oliveira", "мма", {"date": "2026-04-10"})

        self.assertEqual(result, "mma-result")
        mocked_mma.assert_awaited_once_with("Makhachev vs Oliveira", subdiscipline="mma", match_context={"date": "2026-04-10"})

    async def test_raises_for_unknown_discipline(self):
        with self.assertRaises(ValueError):
            await data_router.get_match_data("A vs B", "handball", {})


if __name__ == "__main__":
    unittest.main()